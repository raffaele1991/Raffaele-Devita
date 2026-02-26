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
from concurrent.futures import ProcessPoolExecutor
from functools import partial

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

def train_symbol(symbol: str, n_threads: int = -1):
    print(f"\n{'='*60}")
    print(f"  Addestramento modello: {symbol}")
    print(f"{'='*60}")

    # Trova CSV M5 per questo simbolo (esclude file M30, M15, ecc.)
    pattern  = os.path.join(DATA_DIR_ABS, f"{symbol}_M5*.csv")
    pattern2 = os.path.join(DATA_DIR_ABS, f"{symbol.lower()}_m5*.csv")
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

    # Applica cutoff: allena SOLO su dati precedenti a TRAIN_CUTOFF_DATE
    cutoff = pd.Timestamp(config.TRAIN_CUTOFF_DATE)
    df = df[df.index < cutoff]
    print(f"  [SPLIT] Training limitato a dati < {config.TRAIN_CUTOFF_DATE}")
    print(f"  Candele training: {len(df):,}  (fino a {df.index[-1]})")

    # Feature engineering + struttura SMC
    print("  Rilevamento struttura SMC...")
    df = detect_structure(df)

    print("  Costruzione feature (incluse feature SMC specifiche)...")
    df = build_features(df, symbol=symbol)

    # ── DIAGNOSTICA ──────────────────────────────────────────────────────────
    print(f"  [DIAG] Righe dopo build_features+dropna : {len(df):,}")
    _vol_nan = df["vol_norm"].isna().sum() if "vol_norm" in df.columns else "n/a"
    _bb_nan  = df["bb_position"].isna().sum() if "bb_position" in df.columns else "n/a"
    _adx_nan = df["adx"].isna().sum() if "adx" in df.columns else "n/a"
    print(f"  [DIAG] NaN: vol_norm={_vol_nan}, bb_position={_bb_nan}, adx={_adx_nan}")
    _trend_nz = (df["trend_num"] != 0).sum() if "trend_num" in df.columns else 0
    _ob_nz    = (df["ob_age_norm"] > 0).sum() if "ob_age_norm" in df.columns else 0
    print(f"  [DIAG] trend_num!=0: {_trend_nz:,}  |  ob_age_norm>0: {_ob_nz:,}")
    if "volume" in df.columns:
        _vmin, _vmax, _vmean = df["volume"].min(), df["volume"].max(), df["volume"].mean()
        print(f"  [DIAG] Volume: min={_vmin:.0f}, max={_vmax:.0f}, mean={_vmean:.1f}")
    # ─────────────────────────────────────────────────────────────────────────

    lookahead = config.ML_LOOKAHEAD
    print(f"  Costruzione etichette (lookahead {lookahead} candele = {lookahead * 5} min su M5)...")
    labels = build_labels(df, lookahead=lookahead)
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
    ml = SMCMLModel(symbol, n_threads=n_threads)
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

    cpu_count  = os.cpu_count() or 4
    n_workers  = min(len(config.SYMBOLS), cpu_count)
    n_threads  = max(1, cpu_count // n_workers)
    print(f"CPU disponibili: {cpu_count} — simboli in parallelo: {n_workers} — thread/simbolo: {n_threads}")

    with ProcessPoolExecutor(max_workers=n_workers) as executor:
        list(executor.map(partial(train_symbol, n_threads=n_threads), config.SYMBOLS))

    print("\n\nTraining completato!")
    print("Ora puoi avviare il bot con: python trading_system/bot.py")
