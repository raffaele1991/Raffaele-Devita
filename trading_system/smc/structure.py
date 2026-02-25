"""
SMC Structure Detection
========================
Rileva Break of Structure (BOS) e Change of Character (CHoCH).
"""

import pandas as pd
import numpy as np
from trading_system import config


def find_swing_points(df: pd.DataFrame) -> pd.DataFrame:
    """
    Identifica swing high e swing low sulla serie di candele.
    Aggiunge colonne: swing_high, swing_low (bool).
    Implementazione vettorizzata con pandas rolling (no loop Python).
    """
    n = config.SMC_SWING_LOOKBACK
    df = df.copy()
    window = 2 * n + 1
    rolling_max = df["high"].rolling(window, center=True, min_periods=window).max()
    rolling_min = df["low"].rolling(window, center=True, min_periods=window).min()
    df["swing_high"] = df["high"] == rolling_max
    df["swing_low"]  = df["low"]  == rolling_min
    return df


def detect_structure(df: pd.DataFrame) -> pd.DataFrame:
    """
    Rileva BOS (Break of Structure) e CHoCH (Change of Character).

    BOS bullish  = prezzo rompe sopra l'ultimo swing high (trend continua)
    BOS bearish  = prezzo rompe sotto l'ultimo swing low  (trend continua)
    CHoCH bullish = trend era bearish, ora rompe swing high (inversione)
    CHoCH bearish = trend era bullish, ora rompe swing low  (inversione)

    Aggiunge colonne: bos_bull, bos_bear, choch_bull, choch_bear, trend

    Ottimizzato: usa array NumPy invece di df.iloc/df.at per 10-20x speedup.
    """
    df = find_swing_points(df)

    n       = len(df)
    high    = df["high"].values
    low     = df["low"].values
    close   = df["close"].values
    swing_h = df["swing_high"].values
    swing_l = df["swing_low"].values

    bos_bull   = np.zeros(n, dtype=bool)
    bos_bear   = np.zeros(n, dtype=bool)
    choch_bull = np.zeros(n, dtype=bool)
    choch_bear = np.zeros(n, dtype=bool)
    trend      = np.zeros(n, dtype=np.int8)

    confirm = config.SMC_BOS_CONFIRMATION
    last_swing_high = np.nan
    last_swing_low  = np.nan
    current_trend   = 0

    for i in range(n):
        if swing_h[i]:
            last_swing_high = high[i]
        if swing_l[i]:
            last_swing_low = low[i]

        if not np.isnan(last_swing_high) and i >= confirm:
            if np.all(close[i - confirm + 1: i + 1] > last_swing_high):
                if current_trend == -1:
                    choch_bull[i] = True
                    current_trend = 1
                else:
                    bos_bull[i] = True
                    current_trend = 1

        if not np.isnan(last_swing_low) and i >= confirm:
            if np.all(close[i - confirm + 1: i + 1] < last_swing_low):
                if current_trend == 1:
                    choch_bear[i] = True
                    current_trend = -1
                else:
                    bos_bear[i] = True
                    current_trend = -1

        trend[i] = current_trend

    df = df.copy()
    df["bos_bull"]   = bos_bull
    df["bos_bear"]   = bos_bear
    df["choch_bull"] = choch_bull
    df["choch_bear"] = choch_bear
    df["trend"]      = trend.astype(int)
    return df
