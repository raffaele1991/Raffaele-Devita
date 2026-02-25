"""
ML Model – LightGBM Classifier
================================
Predice se un segnale SMC si tradurrà in un trade vincente.
LightGBM è 10-20x più veloce di sklearn GradientBoosting e
produce accuracy superiore su dataset tabellari finanziari.
"""

import os
import pickle
import numpy as np
import pandas as pd
import lightgbm as lgb
from lightgbm import LGBMClassifier
from pathlib import Path
from sklearn.preprocessing import StandardScaler
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import classification_report, roc_auc_score
from trading_system import config
from .features import FEATURE_COLUMNS

# Percorso assoluto alla cartella modelli
_ROOT       = Path(__file__).parent.parent.parent
_MODELS_DIR = str(_ROOT / config.MODELS_DIR)


class SMCMLModel:
    """
    Wrapper attorno a LGBMClassifier.
    Addestrato una volta, poi usato live per filtrare i segnali SMC.
    """

    def __init__(self, symbol: str):
        self.symbol    = symbol
        self.scaler    = StandardScaler()
        self.model     = LGBMClassifier(
            n_estimators      = config.ML_N_ESTIMATORS,
            num_leaves        = config.ML_NUM_LEAVES,
            learning_rate     = config.ML_LEARNING_RATE,
            subsample         = config.ML_SUBSAMPLE,
            subsample_freq    = 1,
            colsample_bytree  = config.ML_COLSAMPLE_BYTREE,
            min_child_samples = config.ML_MIN_CHILD_SAMPLES,
            reg_alpha         = config.ML_REG_ALPHA,
            reg_lambda        = config.ML_REG_LAMBDA,
            random_state      = config.ML_RANDOM_SEED,
            n_jobs            = -1,
            verbose           = -1,
        )
        self.calibrator = None
        self.is_fitted  = False
        self._model_path = os.path.join(
            _MODELS_DIR, f"model_{symbol.lower()}.pkl"
        )

    # ── TRAINING ──────────────────────────────────────────────────────────────

    def fit(self, X: pd.DataFrame, y: pd.Series) -> dict:
        # Split temporale: 75% train | 10% validation (early stopping) | 15% test
        n = len(X)
        split_train = int(n * 0.75)
        split_val   = int(n * 0.85)

        X_train = X.iloc[:split_train]
        X_val   = X.iloc[split_train:split_val]
        X_test  = X.iloc[split_val:]
        y_train = y.iloc[:split_train]
        y_val   = y.iloc[split_train:split_val]
        y_test  = y.iloc[split_val:]

        # LightGBM non richiede normalizzazione ma la manteniamo per coerenza
        # con il predict_proba usato live (stesso scaler)
        X_train_s = self.scaler.fit_transform(X_train[FEATURE_COLUMNS])
        X_val_s   = self.scaler.transform(X_val[FEATURE_COLUMNS])
        X_test_s  = self.scaler.transform(X_test[FEATURE_COLUMNS])

        # Bilancia le classi tramite sample_weight
        n_neg = (y_train == 0).sum()
        n_pos = (y_train == 1).sum()
        weight_pos = n_neg / n_pos if n_pos > 0 else 1.0
        sample_weights = y_train.map({0: 1.0, 1: weight_pos}).values

        # Callbacks: early stopping + log ogni 100 round
        callbacks = [
            lgb.early_stopping(
                stopping_rounds=config.ML_EARLY_STOPPING_ROUNDS,
                verbose=False,
            ),
            lgb.log_evaluation(period=100),
        ]

        self.model.fit(
            X_train_s, y_train,
            sample_weight = sample_weights,
            eval_set      = [(X_val_s, y_val)],
            callbacks     = callbacks,
        )

        best_iter = self.model.best_iteration_
        print(f"  Early stopping: miglior iterazione = {best_iter}")

        # Calibrazione isotonica sulla validation set
        raw_val = self.model.predict_proba(X_val_s)[:, 1]
        self.calibrator = IsotonicRegression(out_of_bounds="clip")
        self.calibrator.fit(raw_val, y_val.values)

        self.is_fitted = True

        # Metriche sul test set
        y_pred   = self.model.predict(X_test_s)
        raw_test = self.model.predict_proba(X_test_s)[:, 1]
        y_proba  = self.calibrator.predict(raw_test)

        report = classification_report(y_test, y_pred, output_dict=True)
        auc    = roc_auc_score(y_test, y_proba)

        metrics = {
            "accuracy":   report["accuracy"],
            "precision":  report.get("1", {}).get("precision", 0),
            "recall":     report.get("1", {}).get("recall", 0),
            "f1":         report.get("1", {}).get("f1-score", 0),
            "auc":        auc,
            "train_size": len(X_train),
            "test_size":  len(X_test),
            "best_iter":  best_iter,
        }
        return metrics

    # ── INFERENCE ─────────────────────────────────────────────────────────────

    def predict_proba(self, X: pd.DataFrame) -> float:
        """Ritorna la probabilità calibrata che il segnale sia vincente (0.0–1.0)."""
        if not self.is_fitted:
            raise RuntimeError(f"Modello {self.symbol} non addestrato. Lancia train.py prima.")

        features   = X[FEATURE_COLUMNS].iloc[[-1]]
        features_s = self.scaler.transform(features)
        raw_proba  = self.model.predict_proba(features_s)[0][1]

        if self.calibrator is not None:
            proba = float(self.calibrator.predict([raw_proba])[0])
        else:
            proba = float(raw_proba)

        return proba

    def is_confident(self, X: pd.DataFrame) -> bool:
        """True se la confidence supera la soglia configurata."""
        return self.predict_proba(X) >= config.ML_CONFIDENCE_THRESHOLD

    # ── PERSIST ───────────────────────────────────────────────────────────────

    def save(self):
        os.makedirs(_MODELS_DIR, exist_ok=True)
        with open(self._model_path, "wb") as f:
            pickle.dump({
                "scaler":     self.scaler,
                "model":      self.model,
                "calibrator": self.calibrator,
            }, f)
        print(f"[ML] Modello salvato: {self._model_path}")

    def load(self):
        if not os.path.exists(self._model_path):
            raise FileNotFoundError(
                f"Modello non trovato: {self._model_path}\n"
                f"Esegui prima: python trading_system/ml/train.py"
            )
        with open(self._model_path, "rb") as f:
            data = pickle.load(f)
        self.scaler     = data["scaler"]
        self.model      = data["model"]
        self.calibrator = data.get("calibrator", None)
        self.is_fitted  = True
        print(f"[ML] Modello caricato: {self._model_path}")
