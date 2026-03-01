"""
PA Feature Importance Analyzer
================================
Carica i modelli addestrati e mostra l'importanza (split count LightGBM)
delle sole feature Price Action (pa_*) per ogni simbolo.

Uso:
    python PA.py
"""

import os
import sys
import pickle

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

from trading_system import config
from trading_system.ml.features import FEATURE_COLUMNS

MODELS_DIR = os.path.join(ROOT, config.MODELS_DIR)


def load_model(symbol: str) -> dict | None:
    path = os.path.join(MODELS_DIR, f"model_{symbol.lower()}.pkl")
    if not os.path.exists(path):
        print(f"[WARN] Modello non trovato: {path}")
        return None
    with open(path, "rb") as f:
        return pickle.load(f)


def pa_importances(symbol: str) -> None:
    data = load_model(symbol)
    if data is None:
        return

    model = data["model"]

    # LightGBM espone feature_importances_ come array parallelo a FEATURE_COLUMNS
    importances = model.feature_importances_    # array int (split count)

    # Abbina importanza a nome feature
    pairs = list(zip(FEATURE_COLUMNS, importances))

    # Filtra sole feature PA
    pa_pairs = [(name, imp) for name, imp in pairs if name.startswith("pa_")]

    # Ordina per importanza decrescente
    pa_pairs.sort(key=lambda x: x[1], reverse=True)

    print(f"=== {symbol} ===")
    for name, imp in pa_pairs:
        print(f"{name:<25}{imp:>5}")
    print()


if __name__ == "__main__":
    for sym in config.SYMBOLS:
        pa_importances(sym)
