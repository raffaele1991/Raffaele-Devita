"""
ML Model – Gradient Boosting Classifier
=========================================
Predice se un segnale SMC si tradurrà in un trade vincente.
"""

import os
import pickle
import numpy as np
import pandas as pd
from pathlib import Path
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import classification_report, roc_auc_score
from trading_system import config
from .features import FEATURE_COLUMNS

# Percorso assoluto alla cartella modelli
_ROOT       = Path(__file__).parent.parent.parent
_MODELS_DIR = str(_ROOT / config.MODELS_DIR)


class SMCMLModel:
    """
    Wrapper attorno a GradientBoostingClassifier.
    Addestrato una volta, poi usato live per filtrare i segnali SMC.
    """

    def __init__(self, symbol: str):
        self.symbol    = symbol
        self.scaler    = StandardScaler()
        self.model     = GradientBoostingClassifier(
            n_estimators=config.ML_N_ESTIMATORS,
            max_depth=config.ML_MAX_DEPTH,
            learning_rate=config.ML_LEARNING_RATE,
            subsample=config.ML_SUBSAMPLE,
            random_state=config.ML_RANDOM_SEED,
        )
        self.is_fitted = False
        self._model_path = os.path.join(
            _MODELS_DIR, f"model_{symbol.lower()}.pkl"
        )

    # ── TRAINING ──────────────────────────────────────────────────────────────

    def fit(self, X: pd.DataFrame, y: pd.Series) -> dict:
        split = int(len(X) * config.ML_TRAIN_TEST_SPLIT)
        X_train, X_test = X.iloc[:split], X.iloc[split:]
        y_train, y_test = y.iloc[:split], y.iloc[split:]

        X_train_s = self.scaler.fit_transform(X_train[FEATURE_COLUMNS])
        X_test_s  = self.scaler.transform(X_test[FEATURE_COLUMNS])

        self.model.fit(X_train_s, y_train)
        self.is_fitted = True

        y_pred   = self.model.predict(X_test_s)
        y_proba  = self.model.predict_proba(X_test_s)[:, 1]

        report = classification_report(y_test, y_pred, output_dict=True)
        auc    = roc_auc_score(y_test, y_proba)

        metrics = {
            "accuracy":  report["accuracy"],
            "precision": report.get("1", {}).get("precision", 0),
            "recall":    report.get("1", {}).get("recall", 0),
            "f1":        report.get("1", {}).get("f1-score", 0),
            "auc":       auc,
            "train_size": len(X_train),
            "test_size":  len(X_test),
        }
        return metrics

    # ── INFERENCE ─────────────────────────────────────────────────────────────

    def predict_proba(self, X: pd.DataFrame) -> float:
        """Ritorna la probabilità che il segnale sia vincente (0.0 – 1.0)."""
        if not self.is_fitted:
            raise RuntimeError(f"Modello {self.symbol} non addestrato. Lancia train.py prima.")

        features = X[FEATURE_COLUMNS].iloc[[-1]]
        features_s = self.scaler.transform(features)
        proba = self.model.predict_proba(features_s)[0][1]
        return float(proba)

    def is_confident(self, X: pd.DataFrame) -> bool:
        """True se la confidence supera la soglia configurata."""
        return self.predict_proba(X) >= config.ML_CONFIDENCE_THRESHOLD

    # ── PERSIST ───────────────────────────────────────────────────────────────

    def save(self):
        os.makedirs(_MODELS_DIR, exist_ok=True)
        with open(self._model_path, "wb") as f:
            pickle.dump({"scaler": self.scaler, "model": self.model}, f)
        print(f"[ML] Modello salvato: {self._model_path}")

    def load(self):
        if not os.path.exists(self._model_path):
            raise FileNotFoundError(
                f"Modello non trovato: {self._model_path}\n"
                f"Esegui prima: python trading_system/ml/train.py"
            )
        with open(self._model_path, "rb") as f:
            data = pickle.load(f)
        self.scaler    = data["scaler"]
        self.model     = data["model"]
        self.is_fitted = True
        print(f"[ML] Modello caricato: {self._model_path}")
