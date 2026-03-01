"""
Price Action Detector
======================
Combina pattern candlestick + livelli S&R in un segnale PA composito con score 0–100.

Logica scoring:
  Pattern singola candela:
    Pin Bar (forte)      → +40 pts
    Pin Bar (medio)      → +35 pts
    Pin Bar (debole)     → +30 pts
    Engulfing (forte)    → +35 pts
    Engulfing (medio)    → +30 pts
    Engulfing (debole)   → +25 pts
    Morning/Evening Star → +28 pts
    Three Soldiers/Crows → +22 pts
    Marubozu             → +18 pts
    Inside Bar           → +15 pts
    Doji                 → +12 pts

  Livelli S&R vicini (≤ PA_LEVEL_PROXIMITY_ATR × ATR):
    PDH / PDL            → +20 pts
    PWH / PWL            → +15 pts
    Asian High/Low       → +12 pts
    Round level (grande) → +12 pts
    Round level (piccolo)→ +8 pts

  Bonus:
    Pattern allineato con direzione SMC → +10 pts
    Più pattern confermano (≥ 2 direzionali) → +8 pts
    Pattern contro la direzione SMC → -10 pts

  Score finale: clampato 0–100.
  Configurabile: PA_MIN_SCORE in config.py (default 40).
"""

import pandas as pd
import numpy as np
from dataclasses import dataclass, field
from typing import List, Optional

from trading_system import config
from .patterns import detect_all_patterns, CandlePattern
from .levels import find_nearby_levels, SRLevel


@dataclass
class PASignal:
    patterns: List[CandlePattern] = field(default_factory=list)
    nearby_levels: List[SRLevel]  = field(default_factory=list)
    score: int = 0
    direction_bias: str = "neutral"   # "bullish", "bearish", "neutral"
    pattern_names: str  = ""          # human-readable
    level_names: str    = ""          # human-readable

    @property
    def has_confirmation(self) -> bool:
        """True se lo score PA supera la soglia configurata."""
        min_score = getattr(config, 'PA_MIN_SCORE', 0)
        return self.score >= min_score

    @property
    def directional_patterns(self) -> List[CandlePattern]:
        return [p for p in self.patterns if p.direction != "neutral"]

    @property
    def is_bullish(self) -> bool:
        return self.direction_bias == "bullish"

    @property
    def is_bearish(self) -> bool:
        return self.direction_bias == "bearish"


def analyze_pa(
    df: pd.DataFrame,
    symbol: str,
    direction_hint: str = "",
    atr: Optional[float] = None,
) -> PASignal:
    """
    Analizza le ultime candele del DataFrame e ritorna un PASignal.

    Parametri
    ---------
    df             : DataFrame OHLCV (deve avere colonne open/high/low/close).
                     Se presente, usa la colonna 'time' o il DatetimeIndex per i livelli.
    symbol         : simbolo (per round number levels)
    direction_hint : direzione attesa dal segnale SMC ("long" o "short")
    atr            : ATR corrente; calcolato internamente se None

    Ritorno
    -------
    PASignal con patterns trovati, livelli vicini, score e direction_bias.
    """
    if len(df) < 3:
        return PASignal()

    # ── ATR ────────────────────────────────────────────────────────────────────
    if atr is None or atr <= 0:
        tr = pd.concat([
            df["high"] - df["low"],
            (df["high"] - df["close"].shift(1)).abs(),
            (df["low"]  - df["close"].shift(1)).abs(),
        ], axis=1).max(axis=1)
        atr_val = tr.rolling(14).mean().iloc[-1]
        atr = float(atr_val) if not pd.isna(atr_val) else float((df["high"] - df["low"]).mean())

    current_price = float(df.iloc[-1]["close"])

    # ── 1. Pattern candlestick ─────────────────────────────────────────────────
    patterns = detect_all_patterns(df)

    # ── 2. Livelli S&R vicini ──────────────────────────────────────────────────
    proximity_atr = getattr(config, 'PA_LEVEL_PROXIMITY_ATR', 0.5)
    nearby_levels = find_nearby_levels(current_price, df, symbol, atr, proximity_atr)

    # ── 3. Score base dai pattern ──────────────────────────────────────────────
    score = sum(p.score for p in patterns)

    # ── 4. Score dai livelli S&R ───────────────────────────────────────────────
    score += sum(lv.score for lv in nearby_levels)

    # ── 5. Direction bias e bonus allineamento con SMC ─────────────────────────
    direction_bias = "neutral"
    directional = [p for p in patterns if p.direction != "neutral"]

    if directional:
        bull_score = sum(p.score for p in directional if p.direction == "bullish")
        bear_score = sum(p.score for p in directional if p.direction == "bearish")

        if bull_score > bear_score:
            direction_bias = "bullish"
        elif bear_score > bull_score:
            direction_bias = "bearish"

        smc_dir = "bullish" if direction_hint == "long" else ("bearish" if direction_hint == "short" else "")
        if smc_dir:
            if direction_bias == smc_dir:
                score += 10   # bonus: pattern nella stessa direzione del segnale SMC
            elif direction_bias not in ("neutral",):
                score -= 10   # penalità: pattern contro il segnale SMC

    # ── 6. Bonus confluenza multi-pattern ─────────────────────────────────────
    if len(directional) >= 2:
        score += 8

    score = max(0, min(100, score))

    pattern_names = ", ".join(p.name for p in patterns) if patterns else ""
    level_names   = ", ".join(lv.label for lv in nearby_levels) if nearby_levels else ""

    return PASignal(
        patterns=patterns,
        nearby_levels=nearby_levels,
        score=score,
        direction_bias=direction_bias,
        pattern_names=pattern_names,
        level_names=level_names,
    )
