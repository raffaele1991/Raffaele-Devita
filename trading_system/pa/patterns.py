"""
Price Action – Candlestick Patterns
=====================================
Rilevamento pattern candlestick classici su M5.

Pattern supportati:
  - Pin Bar        (hammer / shooting star)        → rigetto da zona chiave
  - Engulfing      (bullish / bearish)              → forte momentum inversivo
  - Inside Bar                                      → compressione → breakout
  - Doji                                            → indecisione su zona OB
  - Marubozu       (bullish / bearish)              → momentum puro senza ombre
  - Morning Star / Evening Star  (3 candele)        → inversione di tendenza
  - Three White Soldiers / Three Black Crows        → continuazione di tendenza
"""

import pandas as pd
import numpy as np
from dataclasses import dataclass
from typing import List, Optional
from trading_system import config


@dataclass
class CandlePattern:
    name: str           # es. "Pin Bar Bull", "Engulfing Bear"
    direction: str      # "bullish", "bearish", "neutral"
    strength: int       # 1 = debole, 2 = medio, 3 = forte
    bar_index: int      # indice nella finestra df (-1 = last candle)
    score: int          # contributo al PA score (0-40)


# ─── HELPER GEOMETRIA CANDELA ──────────────────────────────────────────────────

def _range(h: float, l: float) -> float:
    return max(h - l, 1e-10)

def _body_pct(o: float, h: float, l: float, c: float) -> float:
    return abs(c - o) / _range(h, l)

def _upper_wick_pct(o: float, h: float, l: float, c: float) -> float:
    return (h - max(o, c)) / _range(h, l)

def _lower_wick_pct(o: float, h: float, l: float, c: float) -> float:
    return (min(o, c) - l) / _range(h, l)


# ─── PATTERN SINGOLA CANDELA ───────────────────────────────────────────────────

def detect_pin_bar(
    o: float, h: float, l: float, c: float
) -> Optional[CandlePattern]:
    """
    Pin Bar (Hammer / Shooting Star):
      - Corpo ≤ PA_PIN_BAR_BODY_MAX_PCT (default 35%)
      - Wick di rigetto ≥ PA_PIN_BAR_WICK_MIN_PCT (default 55%)
      - Wick opposto < 20%

    È il pattern PA più importante in confluenza con un OB/FVG:
    il mercato è entrato nella zona e ha immediatamente respinto il prezzo.
    """
    body_max = getattr(config, 'PA_PIN_BAR_BODY_MAX_PCT', 0.35)
    wick_min = getattr(config, 'PA_PIN_BAR_WICK_MIN_PCT', 0.55)

    bp  = _body_pct(o, h, l, c)
    uwp = _upper_wick_pct(o, h, l, c)
    lwp = _lower_wick_pct(o, h, l, c)

    if bp > body_max:
        return None

    # Bullish pin bar: wick inferiore lungo (hammer) → rigetto da area di supporto/OB bull
    if lwp >= wick_min and uwp < 0.20:
        strength = 3 if lwp > 0.70 else (2 if lwp > 0.60 else 1)
        return CandlePattern(
            name="Pin Bar Bull", direction="bullish",
            strength=strength, bar_index=-1,
            score=25 + strength * 5   # 30, 35, 40
        )

    # Bearish pin bar: wick superiore lungo (shooting star) → rigetto da area di resistenza/OB bear
    if uwp >= wick_min and lwp < 0.20:
        strength = 3 if uwp > 0.70 else (2 if uwp > 0.60 else 1)
        return CandlePattern(
            name="Pin Bar Bear", direction="bearish",
            strength=strength, bar_index=-1,
            score=25 + strength * 5   # 30, 35, 40
        )

    return None


def detect_doji(
    o: float, h: float, l: float, c: float
) -> Optional[CandlePattern]:
    """
    Doji: corpo molto piccolo (≤ PA_DOJI_BODY_MAX_PCT, default 10%).
    Su un OB segnala indecisione → probabile inversione.
    """
    body_max = getattr(config, 'PA_DOJI_BODY_MAX_PCT', 0.10)
    if _body_pct(o, h, l, c) <= body_max:
        return CandlePattern(
            name="Doji", direction="neutral",
            strength=1, bar_index=-1,
            score=12
        )
    return None


def detect_marubozu(
    o: float, h: float, l: float, c: float
) -> Optional[CandlePattern]:
    """
    Marubozu: corpo ≥ PA_MARUBOZU_BODY_MIN_PCT (default 80%).
    Segnala forte momentum nella direzione. In confluenza con trend SMC
    conferma che i market maker stanno spingendo in quella direzione.
    """
    body_min = getattr(config, 'PA_MARUBOZU_BODY_MIN_PCT', 0.80)
    if _body_pct(o, h, l, c) >= body_min:
        direction = "bullish" if c > o else "bearish"
        return CandlePattern(
            name=f"Marubozu {'Bull' if direction == 'bullish' else 'Bear'}",
            direction=direction,
            strength=2, bar_index=-1,
            score=18
        )
    return None


# ─── PATTERN DUE CANDELE ────────────────────────────────────────────────────────

def detect_engulfing(
    o1: float, h1: float, l1: float, c1: float,
    o2: float, h2: float, l2: float, c2: float,
) -> Optional[CandlePattern]:
    """
    Engulfing: la candela corrente (2) ingloba il CORPO della precedente (1).
    È il secondo pattern più affidabile dopo il pin bar.

    Bullish engulfing: C1 bearish, C2 bullish e ingloba il corpo di C1.
    Bearish engulfing: C1 bullish, C2 bearish e ingloba il corpo di C1.
    """
    body1 = abs(c1 - o1)
    body2 = abs(c2 - o2)
    min_quality = getattr(config, 'PA_ENGULFING_QUALITY_MIN', 0.5)

    if body1 < 1e-10 or body2 < 1e-10:
        return None

    # Bullish: C1 bearish, C2 bullish che copre tutto il corpo di C1
    if c1 < o1 and c2 > o2:
        top1, bot1 = max(o1, c1), min(o1, c1)
        if o2 <= bot1 and c2 >= top1:
            quality = body2 / body1
            if quality >= min_quality:
                strength = 3 if quality >= 1.5 else (2 if quality >= 1.0 else 1)
                return CandlePattern(
                    name="Engulfing Bull", direction="bullish",
                    strength=strength, bar_index=-1,
                    score=20 + strength * 5   # 25, 30, 35
                )

    # Bearish: C1 bullish, C2 bearish che copre tutto il corpo di C1
    if c1 > o1 and c2 < o2:
        top1, bot1 = max(o1, c1), min(o1, c1)
        if o2 >= top1 and c2 <= bot1:
            quality = body2 / body1
            if quality >= min_quality:
                strength = 3 if quality >= 1.5 else (2 if quality >= 1.0 else 1)
                return CandlePattern(
                    name="Engulfing Bear", direction="bearish",
                    strength=strength, bar_index=-1,
                    score=20 + strength * 5   # 25, 30, 35
                )

    return None


def detect_inside_bar(
    h1: float, l1: float,
    h2: float, l2: float,
) -> Optional[CandlePattern]:
    """
    Inside Bar: la candela corrente (2) è contenuta nel range della precedente (1).
    Indica compressione di volatilità → atteso breakout direzionale.
    In confluenza con OB: la zona sta assorbendo l'offerta/domanda prima del movimento.
    """
    if h2 < h1 and l2 > l1:
        return CandlePattern(
            name="Inside Bar", direction="neutral",
            strength=1, bar_index=-1,
            score=15
        )
    return None


# ─── PATTERN TRE CANDELE ────────────────────────────────────────────────────────

def detect_morning_evening_star(df_slice: pd.DataFrame) -> Optional[CandlePattern]:
    """
    Morning Star (inversione bullish, 3 candele):
      C1: grande candela bearish
      C2: piccola candela (doji / small body) — indecisione al minimo
      C3: grande candela bullish che chiude sopra il midpoint di C1

    Evening Star (inversione bearish, 3 candele):
      C1: grande candela bullish
      C2: piccola candela al massimo
      C3: grande candela bearish che chiude sotto il midpoint di C1
    """
    if len(df_slice) < 3:
        return None

    c1, c2, c3 = df_slice.iloc[-3], df_slice.iloc[-2], df_slice.iloc[-1]
    r1 = _range(c1['high'], c1['low'])
    r3 = _range(c3['high'], c3['low'])

    body2_pct = _body_pct(c2['open'], c2['high'], c2['low'], c2['close'])
    body1_pct = _body_pct(c1['open'], c1['high'], c1['low'], c1['close'])
    body3_pct = _body_pct(c3['open'], c3['high'], c3['low'], c3['close'])

    mid1 = (c1['open'] + c1['close']) / 2

    # Morning Star
    if (c1['close'] < c1['open']          # C1 bearish
        and body2_pct < 0.35              # C2 small body
        and c3['close'] > c3['open']      # C3 bullish
        and body1_pct > 0.50              # C1 corpo solido
        and body3_pct > 0.50              # C3 corpo solido
        and c3['close'] > mid1            # C3 chiude sopra il midpoint di C1
    ):
        return CandlePattern(
            name="Morning Star", direction="bullish",
            strength=3, bar_index=-1, score=28
        )

    # Evening Star
    if (c1['close'] > c1['open']
        and body2_pct < 0.35
        and c3['close'] < c3['open']
        and body1_pct > 0.50
        and body3_pct > 0.50
        and c3['close'] < mid1
    ):
        return CandlePattern(
            name="Evening Star", direction="bearish",
            strength=3, bar_index=-1, score=28
        )

    return None


def detect_three_soldiers_crows(df_slice: pd.DataFrame) -> Optional[CandlePattern]:
    """
    Three White Soldiers (bullish): 3 candele consecutive rialziste, ognuna chiude più in alto.
    Three Black Crows  (bearish):  3 candele consecutive ribassiste, ognuna chiude più in basso.
    Confermano forte momentum direzionale in confluenza con SMC trend.
    """
    if len(df_slice) < 3:
        return None

    c1, c2, c3 = df_slice.iloc[-3], df_slice.iloc[-2], df_slice.iloc[-1]

    # Three White Soldiers
    if (c1['close'] > c1['open']
        and c2['close'] > c2['open']
        and c3['close'] > c3['open']
        and c2['close'] > c1['close']
        and c3['close'] > c2['close']
        and c2['open'] >= c1['open']
        and c3['open'] >= c2['open']
    ):
        return CandlePattern(
            name="Three White Soldiers", direction="bullish",
            strength=2, bar_index=-1, score=22
        )

    # Three Black Crows
    if (c1['close'] < c1['open']
        and c2['close'] < c2['open']
        and c3['close'] < c3['open']
        and c2['close'] < c1['close']
        and c3['close'] < c2['close']
        and c2['open'] <= c1['open']
        and c3['open'] <= c2['open']
    ):
        return CandlePattern(
            name="Three Black Crows", direction="bearish",
            strength=2, bar_index=-1, score=22
        )

    return None


# ─── ENTRY POINT PRINCIPALE ────────────────────────────────────────────────────

def detect_all_patterns(df: pd.DataFrame) -> List[CandlePattern]:
    """
    Rileva tutti i pattern PA sulle ultime candele del DataFrame.
    Ritorna lista di CandlePattern trovati (può essere vuota).
    """
    if len(df) < 3:
        return []

    patterns: List[CandlePattern] = []
    last = df.iloc[-1]
    prev = df.iloc[-2]
    n    = len(df)

    o, h, l, c   = float(last['open']), float(last['high']), float(last['low']), float(last['close'])
    po, ph, pl, pc = float(prev['open']), float(prev['high']), float(prev['low']), float(prev['close'])

    # ── Pattern singola candela ──────────────────────────────────────────────
    pb = detect_pin_bar(o, h, l, c)
    if pb:
        pb.bar_index = n - 1
        patterns.append(pb)

    dj = detect_doji(o, h, l, c)
    if dj:
        dj.bar_index = n - 1
        patterns.append(dj)

    mz = detect_marubozu(o, h, l, c)
    if mz:
        mz.bar_index = n - 1
        patterns.append(mz)

    # ── Pattern due candele ──────────────────────────────────────────────────
    eng = detect_engulfing(po, ph, pl, pc, o, h, l, c)
    if eng:
        eng.bar_index = n - 1
        patterns.append(eng)

    ib = detect_inside_bar(ph, pl, h, l)
    if ib:
        ib.bar_index = n - 1
        patterns.append(ib)

    # ── Pattern tre candele ──────────────────────────────────────────────────
    star = detect_morning_evening_star(df.iloc[-3:].reset_index(drop=True))
    if star:
        star.bar_index = n - 1
        patterns.append(star)

    sol = detect_three_soldiers_crows(df.iloc[-3:].reset_index(drop=True))
    if sol:
        sol.bar_index = n - 1
        patterns.append(sol)

    return patterns
