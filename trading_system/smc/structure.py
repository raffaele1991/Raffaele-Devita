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
    """
    df = find_swing_points(df)
    df["bos_bull"]   = False
    df["bos_bear"]   = False
    df["choch_bull"] = False
    df["choch_bear"] = False
    df["trend"]      = 0   # 1 = bullish, -1 = bearish, 0 = undefined

    confirm = config.SMC_BOS_CONFIRMATION
    last_swing_high = None
    last_swing_low  = None
    current_trend   = 0

    for i in range(len(df)):
        row = df.iloc[i]

        if row["swing_high"]:
            last_swing_high = row["high"]

        if row["swing_low"]:
            last_swing_low = row["low"]

        # Verifica rottura confermata (chiusura oltre il livello per N candele)
        if last_swing_high is not None and i >= confirm:
            closes = df["close"].iloc[i - confirm + 1: i + 1]
            if all(c > last_swing_high for c in closes):
                if current_trend == -1:
                    df.at[df.index[i], "choch_bull"] = True
                    current_trend = 1
                else:
                    df.at[df.index[i], "bos_bull"] = True
                    current_trend = 1

        if last_swing_low is not None and i >= confirm:
            closes = df["close"].iloc[i - confirm + 1: i + 1]
            if all(c < last_swing_low for c in closes):
                if current_trend == 1:
                    df.at[df.index[i], "choch_bear"] = True
                    current_trend = -1
                else:
                    df.at[df.index[i], "bos_bear"] = True
                    current_trend = -1

        df.at[df.index[i], "trend"] = current_trend

    return df
