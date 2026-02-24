"""
SMC Zones Detection
====================
Order Block, Fair Value Gap, Liquidity Levels.
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
    """
    blocks = []
    lookback = config.OB_LOOKBACK
    min_body = config.OB_MIN_CANDLE_BODY_PCT

    for i in range(lookback, len(df)):
        row = df.iloc[i]

        if row.get("bos_bull", False) or row.get("choch_bull", False):
            # Cerca l'ultima candela bearish prima di questo BOS
            for j in range(i - 1, max(i - lookback, 0), -1):
                c = df.iloc[j]
                candle_range = c["high"] - c["low"]
                body = abs(c["close"] - c["open"])
                if candle_range == 0:
                    continue
                if c["close"] < c["open"] and body / candle_range >= min_body:
                    blocks.append(OrderBlock(
                        index=j,
                        direction="bullish",
                        top=c["high"],
                        bottom=c["low"],
                        origin_close=c["close"],
                    ))
                    break

        if row.get("bos_bear", False) or row.get("choch_bear", False):
            # Cerca l'ultima candela bullish prima di questo BOS
            for j in range(i - 1, max(i - lookback, 0), -1):
                c = df.iloc[j]
                candle_range = c["high"] - c["low"]
                body = abs(c["close"] - c["open"])
                if candle_range == 0:
                    continue
                if c["close"] > c["open"] and body / candle_range >= min_body:
                    blocks.append(OrderBlock(
                        index=j,
                        direction="bearish",
                        top=c["high"],
                        bottom=c["low"],
                        origin_close=c["close"],
                    ))
                    break

    # Invalida OB solo per i bar SUCCESSIVI alla sua formazione
    # Registra anche il bar esatto in cui avviene l'invalidazione
    for i in range(len(df)):
        price = df["close"].iloc[i]
        for ob in blocks:
            if not ob.active:
                continue
            if i <= ob.index:          # non invalidare prima che l'OB si formi
                continue
            if ob.direction == "bullish" and price < ob.bottom:
                ob.active         = False
                ob.invalidated_at = i
            if ob.direction == "bearish" and price > ob.top:
                ob.active         = False
                ob.invalidated_at = i

    return blocks


def find_fvg(df: pd.DataFrame, symbol: str) -> List[FairValueGap]:
    """
    Fair Value Gap = vuoto tra candela i-1 e candela i+1 (la candela i è quella "di impulso").
    FVG bullish: low[i+1] > high[i-1]
    FVG bearish: high[i+1] < low[i-1]
    """
    gaps = []
    min_size = config.FVG_MIN_SIZE_PIPS.get(symbol, 0.0005)

    for i in range(1, len(df) - 1):
        prev = df.iloc[i - 1]
        curr = df.iloc[i]
        nxt  = df.iloc[i + 1]

        # FVG bullish
        if nxt["low"] > prev["high"]:
            size = nxt["low"] - prev["high"]
            if size >= min_size:
                gaps.append(FairValueGap(
                    index=i,
                    direction="bullish",
                    top=nxt["low"],
                    bottom=prev["high"],
                ))

        # FVG bearish
        if nxt["high"] < prev["low"]:
            size = prev["low"] - nxt["high"]
            if size >= min_size:
                gaps.append(FairValueGap(
                    index=i,
                    direction="bearish",
                    top=prev["low"],
                    bottom=nxt["high"],
                ))

    # Marca FVG come riempiti solo per bar SUCCESSIVI alla formazione
    for i in range(len(df)):
        price_high = df["high"].iloc[i]
        price_low  = df["low"].iloc[i]
        for fvg in gaps:
            if fvg.filled:
                continue
            if i <= fvg.index:         # non riempire prima che il FVG si formi
                continue
            if fvg.direction == "bullish" and price_low <= fvg.bottom:
                fvg.filled    = True
                fvg.filled_at = i
            if fvg.direction == "bearish" and price_high >= fvg.top:
                fvg.filled    = True
                fvg.filled_at = i

    return gaps


def find_liquidity_levels(df: pd.DataFrame, symbol: str) -> List[LiquidityLevel]:
    """
    Trova Equal Highs / Equal Lows = zone di liquidità dove gli stop si accumulano.
    """
    levels = []
    lookback = config.LIQ_LOOKBACK
    tol = config.LIQ_TOLERANCE_PIPS.get(symbol, 0.0002)

    highs = df["high"].values
    lows  = df["low"].values

    for i in range(lookback, len(df)):
        window_h = highs[i - lookback: i]
        window_l = lows[i - lookback: i]

        # Equal highs: almeno 2 swing high sullo stesso livello
        similar_highs = [h for h in window_h if abs(h - highs[i]) <= tol]
        if len(similar_highs) >= 2:
            levels.append(LiquidityLevel(
                price=highs[i],
                direction="highs",
            ))

        # Equal lows
        similar_lows = [l for l in window_l if abs(l - lows[i]) <= tol]
        if len(similar_lows) >= 2:
            levels.append(LiquidityLevel(
                price=lows[i],
                direction="lows",
            ))

    return levels
