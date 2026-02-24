"""
SMC Detector – punto di ingresso principale
=============================================
Combina structure + zones e produce un segnale SMC per ogni candela.
"""

import pandas as pd
from dataclasses import dataclass
from typing import Optional
from .structure import detect_structure
from .zones import find_order_blocks, find_fvg, find_liquidity_levels


@dataclass
class SMCSignal:
    direction: str          # "long" o "short"
    entry_price: float
    sl_price: float
    tp_price: float
    reason: str             # descrizione del setup
    ob_top: float = 0.0
    ob_bottom: float = 0.0
    fvg_top: float = 0.0
    fvg_bottom: float = 0.0
    liquidity_swept: bool = False
    trend_aligned: bool = False


class SMCDetector:
    """
    Analizza un DataFrame OHLCV e restituisce un segnale SMC se presente.
    Il segnale richiede:
      1. Trend confermato (BOS / CHoCH)
      2. Prezzo ritorna su un Order Block attivo
      3. Presence di FVG nella stessa zona
      4. (Bonus) Sweep di liquidità prima dell'inversione
    """

    def __init__(self, symbol: str):
        self.symbol = symbol

    def analyze(self, df: pd.DataFrame) -> Optional[SMCSignal]:
        """
        df: DataFrame con colonne open, high, low, close, volume
            ordinato dal più vecchio al più recente.
        Ritorna SMCSignal se c'è un setup valido sull'ultima candela, None altrimenti.
        """
        if len(df) < 60:
            return None

        df = detect_structure(df)
        order_blocks = find_order_blocks(df, self.symbol)
        fvgs         = find_fvg(df, self.symbol)
        liq_levels   = find_liquidity_levels(df, self.symbol)

        last      = df.iloc[-1]
        last_idx  = len(df) - 1
        trend     = last["trend"]   # 1 bullish, -1 bearish, 0 undefined

        if trend == 0:
            return None

        current_price = last["close"]

        # ── LONG SETUP ─────────────────────────────────────────────────────
        if trend == 1:
            active_bull_obs = [
                ob for ob in order_blocks
                if ob.direction == "bullish"
                and ob.active
                and ob.bottom <= current_price <= ob.top
            ]

            for ob in active_bull_obs:
                # Cerca un FVG bullish nella stessa zona
                fvg_in_zone = next(
                    (f for f in fvgs
                     if f.direction == "bullish"
                     and not f.filled
                     and f.bottom >= ob.bottom
                     and f.top <= ob.top),
                    None
                )

                # Liquidity sweep: prezzo ha preso i lows prima di rimbalzare?
                liq_swept = any(
                    lv.direction == "lows"
                    and abs(lv.price - ob.bottom) / ob.bottom < 0.005
                    for lv in liq_levels
                )

                entry = current_price
                sl    = ob.bottom * 0.9995   # leggermente sotto l'OB
                risk  = entry - sl
                if risk <= 0:
                    continue
                tp = entry + risk * 2.0      # R:R 1:2 minimo

                reason_parts = ["Bullish OB in uptrend"]
                if fvg_in_zone:
                    reason_parts.append("FVG confluence")
                if liq_swept:
                    reason_parts.append("Liquidity swept")

                return SMCSignal(
                    direction="long",
                    entry_price=entry,
                    sl_price=sl,
                    tp_price=tp,
                    reason=" + ".join(reason_parts),
                    ob_top=ob.top,
                    ob_bottom=ob.bottom,
                    fvg_top=fvg_in_zone.top if fvg_in_zone else 0,
                    fvg_bottom=fvg_in_zone.bottom if fvg_in_zone else 0,
                    liquidity_swept=liq_swept,
                    trend_aligned=True,
                )

        # ── SHORT SETUP ────────────────────────────────────────────────────
        if trend == -1:
            active_bear_obs = [
                ob for ob in order_blocks
                if ob.direction == "bearish"
                and ob.active
                and ob.bottom <= current_price <= ob.top
            ]

            for ob in active_bear_obs:
                fvg_in_zone = next(
                    (f for f in fvgs
                     if f.direction == "bearish"
                     and not f.filled
                     and f.bottom >= ob.bottom
                     and f.top <= ob.top),
                    None
                )

                liq_swept = any(
                    lv.direction == "highs"
                    and abs(lv.price - ob.top) / ob.top < 0.005
                    for lv in liq_levels
                )

                entry = current_price
                sl    = ob.top * 1.0005
                risk  = sl - entry
                if risk <= 0:
                    continue
                tp = entry - risk * 2.0

                reason_parts = ["Bearish OB in downtrend"]
                if fvg_in_zone:
                    reason_parts.append("FVG confluence")
                if liq_swept:
                    reason_parts.append("Liquidity swept")

                return SMCSignal(
                    direction="short",
                    entry_price=entry,
                    sl_price=sl,
                    tp_price=tp,
                    reason=" + ".join(reason_parts),
                    ob_top=ob.top,
                    ob_bottom=ob.bottom,
                    fvg_top=fvg_in_zone.top if fvg_in_zone else 0,
                    fvg_bottom=fvg_in_zone.bottom if fvg_in_zone else 0,
                    liquidity_swept=liq_swept,
                    trend_aligned=True,
                )

        return None
