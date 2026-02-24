"""
Feature Engineering
====================
Costruisce le feature per il modello ML partendo dai dati OHLCV + output SMC.
"""

import pandas as pd
import numpy as np
from trading_system import config


def add_candle_features(df: pd.DataFrame) -> pd.DataFrame:
    """Feature basate sulla singola candela e sul contesto vicino."""
    df = df.copy()

    # Corpo e ombre
    df["body"]          = abs(df["close"] - df["open"])
    df["upper_shadow"]  = df["high"] - df[["open", "close"]].max(axis=1)
    df["lower_shadow"]  = df[["open", "close"]].min(axis=1) - df["low"]
    df["range"]         = df["high"] - df["low"]
    df["body_pct"]      = df["body"] / df["range"].replace(0, np.nan)
    df["is_bullish"]    = (df["close"] > df["open"]).astype(int)

    # Rendimenti
    df["ret_1"]  = df["close"].pct_change(1)
    df["ret_3"]  = df["close"].pct_change(3)
    df["ret_5"]  = df["close"].pct_change(5)
    df["ret_10"] = df["close"].pct_change(10)
    df["ret_20"] = df["close"].pct_change(20)

    return df


def add_moving_averages(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    for p in [9, 21, 50, 100, 200]:
        df[f"ema_{p}"] = df["close"].ewm(span=p, adjust=False).mean()
        df[f"close_vs_ema_{p}"] = (df["close"] - df[f"ema_{p}"]) / df[f"ema_{p}"]
    return df


def add_volatility(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    period = config.ATR_PERIOD

    high_low   = df["high"] - df["low"]
    high_close = (df["high"] - df["close"].shift(1)).abs()
    low_close  = (df["low"]  - df["close"].shift(1)).abs()
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    df["atr"] = tr.rolling(period).mean()
    df["atr_pct"] = df["atr"] / df["close"]

    # Volatilità storica
    df["vol_5"]  = df["ret_1"].rolling(5).std()
    df["vol_20"] = df["ret_1"].rolling(20).std()

    return df


def add_momentum(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    # RSI
    delta = df["close"].diff()
    gain  = delta.clip(lower=0).rolling(14).mean()
    loss  = (-delta.clip(upper=0)).rolling(14).mean()
    rs    = gain / loss.replace(0, np.nan)
    df["rsi"] = 100 - 100 / (1 + rs)
    df["rsi_norm"] = (df["rsi"] - 50) / 50   # normalizzato -1..+1

    # MACD
    ema12 = df["close"].ewm(span=12, adjust=False).mean()
    ema26 = df["close"].ewm(span=26, adjust=False).mean()
    df["macd"]        = ema12 - ema26
    df["macd_signal"] = df["macd"].ewm(span=9, adjust=False).mean()
    df["macd_hist"]   = df["macd"] - df["macd_signal"]
    df["macd_norm"]   = df["macd"] / df["close"]

    # Stochastic
    low14  = df["low"].rolling(14).min()
    high14 = df["high"].rolling(14).max()
    df["stoch_k"] = 100 * (df["close"] - low14) / (high14 - low14).replace(0, np.nan)
    df["stoch_d"] = df["stoch_k"].rolling(3).mean()

    return df


def add_smc_features(df: pd.DataFrame) -> pd.DataFrame:
    """Feature derivate dall'analisi SMC già presente nel DataFrame."""
    df = df.copy()
    df["trend_num"]  = df.get("trend", pd.Series(0, index=df.index))
    df["bos_bull_n"] = df.get("bos_bull", pd.Series(False, index=df.index)).astype(int)
    df["bos_bear_n"] = df.get("bos_bear", pd.Series(False, index=df.index)).astype(int)
    df["choch_bull_n"] = df.get("choch_bull", pd.Series(False, index=df.index)).astype(int)
    df["choch_bear_n"] = df.get("choch_bear", pd.Series(False, index=df.index)).astype(int)

    # Quante candele fa è stato l'ultimo BOS
    bos_events = df["bos_bull_n"] | df["bos_bear_n"] | df["choch_bull_n"] | df["choch_bear_n"]
    df["bars_since_structure"] = bos_events[::-1].cumsum()[::-1].where(bos_events, 0)

    return df


def build_features(df: pd.DataFrame) -> pd.DataFrame:
    """Pipeline completa di feature engineering."""
    df = add_candle_features(df)
    df = add_moving_averages(df)
    df = add_volatility(df)
    df = add_momentum(df)
    df = add_smc_features(df)
    df = df.dropna()
    return df


FEATURE_COLUMNS = [
    # Candela
    "body_pct", "upper_shadow", "lower_shadow", "is_bullish",
    # Rendimenti
    "ret_1", "ret_3", "ret_5", "ret_10", "ret_20",
    # EMA distance
    "close_vs_ema_9", "close_vs_ema_21", "close_vs_ema_50",
    "close_vs_ema_100", "close_vs_ema_200",
    # Volatilità
    "atr_pct", "vol_5", "vol_20",
    # Momentum
    "rsi_norm", "macd_norm", "macd_hist", "stoch_k", "stoch_d",
    # SMC
    "trend_num", "bos_bull_n", "bos_bear_n", "choch_bull_n", "choch_bear_n",
    "bars_since_structure",
]


def build_labels(df: pd.DataFrame, lookahead: int = 10, min_move_atr: float = 1.0) -> pd.Series:
    """
    Label binaria: 1 se il trade nella direzione del trend era vincente.
    Un trade è vincente se il prezzo si muove di min_move_atr * ATR
    nella direzione corretta entro `lookahead` candele senza toccare prima lo SL.
    """
    labels = pd.Series(0, index=df.index)
    atr = df["atr"].values
    trend = df["trend_num"].values
    close = df["close"].values
    high  = df["high"].values
    low   = df["low"].values

    for i in range(len(df) - lookahead):
        t = trend[i]
        if t == 0:
            continue

        sl_dist = atr[i] * config.ATR_SL_MULTIPLIER
        entry   = close[i]

        if t == 1:  # long
            sl = entry - sl_dist
            tp = entry + sl_dist * config.MIN_RISK_REWARD
            hit_sl = any(low[i+1:i+lookahead+1]  <= sl)
            hit_tp = any(high[i+1:i+lookahead+1] >= tp)
            if hit_tp and not hit_sl:
                labels.iloc[i] = 1
            elif hit_sl:
                labels.iloc[i] = 0

        else:  # short
            sl = entry + sl_dist
            tp = entry - sl_dist * config.MIN_RISK_REWARD
            hit_sl = any(high[i+1:i+lookahead+1] >= sl)
            hit_tp = any(low[i+1:i+lookahead+1]  <= tp)
            if hit_tp and not hit_sl:
                labels.iloc[i] = 1
            elif hit_sl:
                labels.iloc[i] = 0

    return labels
