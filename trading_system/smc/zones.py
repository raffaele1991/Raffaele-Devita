"""
SMC Zones Detection
====================
Order Block, Fair Value Gap, Liquidity Levels.

Ottimizzato: numpy array access al posto di df.iloc/df.at;
invalidazione OB/FVG vettorizzata per-zona (invece di O(n × num_zone) Python).
"""

import pandas as pd
import numpy as np
from dataclasses import dataclass, field
from typing import List
from trading_system import config


@dataclass
class OrderBlock:
    index: int
    direction: str        # "bullish" o "bearish"
    top: float
    bottom: float
    origin_close: float
    active: bool = True          # False quando il prezzo ci ritorna e la invalida
    invalidated_at: int = -1     # bar index a cui è stato invalidato (-1 = mai)

    @property
    def midpoint(self):
        return (self.top + self.bottom) / 2


@dataclass
class FairValueGap:
    index: int
    direction: str        # "bullish" o "bearish"
    top: float
    bottom: float
    filled: bool = False
    filled_at: int = -1  # bar index a cui è stato riempito (-1 = mai)

    @property
    def size(self):
        return self.top - self.bottom


@dataclass
class LiquidityLevel:
    price: float
    direction: str        # "highs" o "lows"
    touched: bool = False


def find_order_blocks(df: pd.DataFrame, symbol: str) -> List[OrderBlock]:
    """
    Order Block bullish  = ultima candela ribassista prima di un BOS bullish
    Order Block bearish  = ultima candela rialzista prima di un BOS bearish

    Ottimizzato:
    - detection: numpy array invece di df.iloc[j]
    - invalidazione: per-OB numpy scan invece di O(n × num_OB) loop Python
    """
    blocks   = []
    lookback = config.OB_LOOKBACK
    min_body = config.OB_MIN_CANDLE_BODY_PCT

    n      = len(df)
    high   = df["high"].values
    low    = df["low"].values
    open_  = df["open"].values
    close  = df["close"].values

    bos_bull_v   = df.get("bos_bull",   pd.Series(False, index=df.index)).values
    choch_bull_v = df.get("choch_bull", pd.Series(False, index=df.index)).values
    bos_bear_v   = df.get("bos_bear",   pd.Series(False, index=df.index)).values
    choch_bear_v = df.get("choch_bear", pd.Series(False, index=df.index)).values

    for i in range(lookback, n):
        if bos_bull_v[i] or choch_bull_v[i]:
            for j in range(i - 1, max(i - lookback, -1), -1):
                rng  = high[j] - low[j]
                body = abs(close[j] - open_[j])
                if rng == 0:
                    continue
                if close[j] < open_[j] and body / rng >= min_body:
                    blocks.append(OrderBlock(
                        index=j, direction="bullish",
                        top=float(high[j]), bottom=float(low[j]),
                        origin_close=float(close[j]),
                    ))
                    break

        if bos_bear_v[i] or choch_bear_v[i]:
            for j in range(i - 1, max(i - lookback, -1), -1):
                rng  = high[j] - low[j]
                body = abs(close[j] - open_[j])
                if rng == 0:
                    continue
                if close[j] > open_[j] and body / rng >= min_body:
                    blocks.append(OrderBlock(
                        index=j, direction="bearish",
                        top=float(high[j]), bottom=float(low[j]),
                        origin_close=float(close[j]),
                    ))
                    break

    # ── Invalidazione vettorizzata ────────────────────────────────────────────
    # Per ogni OB cerca il PRIMO bar successivo che lo invalida con np.where
    # (sostituisce l'O(n × num_OB) doppio loop Python originale)
    for ob in blocks:
        start = ob.index + 1
        if start >= n:
            continue
        if ob.direction == "bullish":
            hits = np.where(close[start:] < ob.bottom)[0]
        else:
            hits = np.where(close[start:] > ob.top)[0]
        if len(hits) > 0:
            ob.invalidated_at = start + int(hits[0])
            ob.active = False

    return blocks


def find_fvg(df: pd.DataFrame, symbol: str) -> List[FairValueGap]:
    """
    Fair Value Gap = vuoto tra candela i-1 e candela i+1 (la candela i è quella "di impulso").
    FVG bullish: low[i+1] > high[i-1]
    FVG bearish: high[i+1] < low[i-1]

    Ottimizzato:
    - detection: completamente vettorizzata con numpy shift
    - invalidazione: per-FVG numpy scan invece di O(n × num_FVG) loop Python
    """
    gaps     = []
    min_size = config.FVG_MIN_SIZE_PIPS.get(symbol, 0.0005)

    n    = len(df)
    high = df["high"].values
    low  = df["low"].values

    if n >= 3:
        # Vettorizzato: per i = 1 .. n-2
        # bull_size = low[i+1] - high[i-1]  →  low[2:] - high[:-2]
        # bear_size = low[i-1] - high[i+1]  →  low[:-2] - high[2:]
        bull_size = low[2:] - high[:-2]    # shape (n-2,)
        bear_size = low[:-2] - high[2:]    # shape (n-2,)

        bull_idx = np.where(bull_size >= min_size)[0] + 1  # +1 per offset impulso
        bear_idx = np.where(bear_size >= min_size)[0] + 1

        for i in bull_idx:
            gaps.append(FairValueGap(
                index=int(i), direction="bullish",
                top=float(low[i + 1]), bottom=float(high[i - 1]),
            ))

        for i in bear_idx:
            gaps.append(FairValueGap(
                index=int(i), direction="bearish",
                top=float(low[i - 1]), bottom=float(high[i + 1]),
            ))

    # ── Invalidazione vettorizzata ────────────────────────────────────────────
    for fvg in gaps:
        start = fvg.index + 1
        if start >= n:
            continue
        if fvg.direction == "bullish":
            hits = np.where(low[start:] <= fvg.bottom)[0]
        else:
            hits = np.where(high[start:] >= fvg.top)[0]
        if len(hits) > 0:
            fvg.filled_at = start + int(hits[0])
            fvg.filled = True

    return gaps


def find_liquidity_levels(df: pd.DataFrame, symbol: str) -> List[LiquidityLevel]:
    """
    Trova Equal Highs / Equal Lows = zone di liquidità dove gli stop si accumulano.

    Ottimizzato: numpy vectorized inner ops invece di Python list comprehension.
    """
    levels   = []
    lookback = config.LIQ_LOOKBACK
    tol      = config.LIQ_TOLERANCE_PIPS.get(symbol, 0.0002)

    highs = df["high"].values
    lows  = df["low"].values
    n     = len(df)

    for i in range(lookback, n):
        window_h = highs[i - lookback: i]
        window_l = lows[i - lookback: i]

        if np.sum(np.abs(window_h - highs[i]) <= tol) >= 2:
            levels.append(LiquidityLevel(price=float(highs[i]), direction="highs"))

        if np.sum(np.abs(window_l - lows[i]) <= tol) >= 2:
            levels.append(LiquidityLevel(price=float(lows[i]), direction="lows"))

    return levels
