"""
Script di Training
===================
Uso:
    python trading_system/ml/train.py

Legge i CSV da trading_system/data/, addestra il modello per ogni simbolo
e salva i file .pkl in trading_system/models/.

Formato CSV atteso da MT5:
    <DATE>	<TIME>	<OPEN>	<HIGH>	<LOW>	<CLOSE>	<TICKVOL>	<VOL>	<SPREAD>
oppure:
    Date,Time,Open,High,Low,Close,Volume
"""

import os
import sys
import glob
import pandas as pd

# Aggiungi root al path
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from trading_system import config

# Percorsi assoluti (indipendenti dalla working directory)
DATA_DIR_ABS   = os.path.join(ROOT, config.DATA_DIR)
MODELS_DIR_ABS = os.path.join(ROOT, config.MODELS_DIR)
from trading_system.smc.structure import detect_structure
from trading_system.ml.features import build_features, build_labels, FEATURE_COLUMNS
from trading_system.ml.model import SMCMLModel


# ─── CARICA CSV MT5 ───────────────────────────────────────────────────────────

def load_mt5_csv(filepath: str) -> pd.DataFrame:
    """
    Gestisce sia il formato tab-separated di MT5 che il formato CSV standard.
    """
    try:
        # Prova formato MT5 con tab e colonne angolari
        df = pd.read_csv(filepath, sep="\t")
        df.columns = [c.strip("<>").lower() for c in df.columns]

        # Se la lettura tab ha prodotto una sola colonna, il file è CSV a virgola
        if len(df.columns) < 4:
            raise ValueError("Formato tab non valido — provo CSV a virgola")

        # Colonne attese: date, time, open, high, low, close, tickvol, vol, spread
        if "date" in df.columns and "time" in df.columns:
            df["datetime"] = pd.to_datetime(df["date"] + " " + df["time"])
        elif "datetime" in df.columns:
            df["datetime"] = pd.to_datetime(df["datetime"])
        else:
            raise ValueError("Colonna datetime non trovata nel formato tab")

        df = df.rename(columns={
            "tickvol": "volume",
            "vol":     "volume_real",
        })

    except Exception:
        # Prova formato CSV standard (virgola)
        df = pd.read_csv(filepath)
        df.columns = [c.strip().lower() for c in df.columns]
        if "date" in df.columns and "time" in df.columns:
            df["datetime"] = pd.to_datetime(df["date"].astype(str) + " " + df["time"].astype(str))
        elif "datetime" in df.columns:
            df["datetime"] = pd.to_datetime(df["datetime"])

    df = df.set_index("datetime").sort_index()
    df = df[["open", "high", "low", "close", "volume"]].dropna()
    df = df.astype(float)
    return df


# ─── TRAINING ─────────────────────────────────────────────────────────────────

def train_symbol(symbol: str):
    print(f"\n{'='*60}")
    print(f"  Addestramento modello: {symbol}")
    print(f"{'='*60}")

    # Trova CSV per questo simbolo (deduplicato per evitare doppio caricamento)
    pattern  = os.path.join(DATA_DIR_ABS, f"{symbol}*.csv")
    pattern2 = os.path.join(DATA_DIR_ABS, f"{symbol.lower()}*.csv")
    files = list(dict.fromkeys(glob.glob(pattern) + glob.glob(pattern2)))

    if not files:
        print(f"[WARN] Nessun CSV trovato per {symbol} in {config.DATA_DIR}/")
        print(f"       Rinomina il file come: {symbol}_M5.csv")
        return

    # Carica e concatena tutti i file trovati
    dfs = []
    for f in files:
        print(f"  Carico: {f}")
        try:
            dfs.append(load_mt5_csv(f))
        except Exception as e:
            print(f"  [ERRORE] {f}: {e}")

    if not dfs:
        print(f"[ERRORE] Impossibile caricare dati per {symbol}")
        return

    df = pd.concat(dfs).sort_index().drop_duplicates()
    print(f"  Candele totali caricate: {len(df):,}")
    print(f"  Periodo: {df.index[0]} → {df.index[-1]}")

    # Feature engineering + struttura SMC
    print("  Rilevamento struttura SMC...")
    df = detect_structure(df)

    print("  Costruzione feature (incluse feature SMC specifiche)...")
    df = build_features(df, symbol=symbol)

    print("  Costruzione etichette (lookahead 40 candele)...")
    labels = build_labels(df, lookahead=40)
    df["label"] = labels

    # Rimuovi righe senza etichetta o feature incomplete
    df = df.dropna(subset=FEATURE_COLUMNS + ["label"])
    df = df[df["trend_num"] != 0]    # trada solo quando c'è un trend
    df = df[df["ob_age_norm"] > 0]   # solo bar con OB attivo = segnali reali SMC

    win_rate = df["label"].mean() * 100
    print(f"  Campioni OB-segnale: {len(df):,}  |  Win rate storico: {win_rate:.1f}%")

    if len(df) < 500:
        print(f"[WARN] Troppo pochi campioni ({len(df)}). Servono almeno 500.")
        return

    X = df[FEATURE_COLUMNS]
    y = df["label"]

    # Train
    print("  Addestramento in corso...")
    ml = SMCMLModel(symbol)
    metrics = ml.fit(X, y)

    print(f"\n  ── RISULTATI TEST ──────────────────────────────")
    print(f"  Accuracy : {metrics['accuracy']:.3f}")
    print(f"  Precision: {metrics['precision']:.3f}")
    print(f"  Recall   : {metrics['recall']:.3f}")
    print(f"  F1       : {metrics['f1']:.3f}")
    print(f"  AUC-ROC  : {metrics['auc']:.3f}")
    print(f"  Train set: {metrics['train_size']:,} campioni")
    print(f"  Test set : {metrics['test_size']:,} campioni")

    ml.save()
    print(f"\n  Modello salvato in: {config.MODELS_DIR}/model_{symbol.lower()}.pkl")


# ─── MAIN ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("\nSistema di Training SMC + ML")
    print("--------------------------------")
    print(f"Data directory: {config.DATA_DIR}")
    print(f"Models directory: {config.MODELS_DIR}")

    print(f"Data directory (assoluto): {DATA_DIR_ABS}")
    print(f"Models directory (assoluto): {MODELS_DIR_ABS}")

    # Controlla che la cartella data esista e contenga file
    if not os.path.exists(DATA_DIR_ABS):
        print(f"\n[ERRORE] Cartella dati non trovata: {DATA_DIR_ABS}")
        sys.exit(1)

    csv_files = glob.glob(os.path.join(DATA_DIR_ABS, "*.csv"))
    if not csv_files:
        print(f"\n[ERRORE] Nessun CSV nella cartella {DATA_DIR_ABS}/")
        print(f"  File presenti: {os.listdir(DATA_DIR_ABS)}")
        sys.exit(1)

    print(f"CSV trovati: {[os.path.basename(f) for f in csv_files]}")
    os.makedirs(MODELS_DIR_ABS, exist_ok=True)

    for symbol in config.SYMBOLS:
        train_symbol(symbol)

    print("\n\nTraining completato!")
    print("Ora puoi avviare il bot con: python trading_system/bot.py")
