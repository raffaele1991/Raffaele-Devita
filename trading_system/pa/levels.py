"""
Price Action – Support & Resistance Levels
============================================
Livelli chiave dove il prezzo tende a reagire:

  PDH / PDL   — Previous Day High / Low       (importanza 3 — massima)
  PWH / PWL   — Previous Week High / Low      (importanza 3 — massima)
  Round       — Livelli psicologici tondi      (importanza 1-2)
  Asian H/L   — Range sessione asiatica        (importanza 2)

In confluenza con un OB: se il prezzo arriva a un OB che coincide
con un PDH o un livello round, la probabilità di reazione aumenta
significativamente (doppia liquidità accumulata lì).
"""

import pandas as pd
import numpy as np
from dataclasses import dataclass
from typing import List
from trading_system import config


@dataclass
class SRLevel:
    price: float
    label: str           # es. "PDH", "PWL", "Round 2700", "Asian High"
    level_type: str      # "pdh", "pdl", "pwh", "pwl", "round", "session"
    importance: int      # 1-3 (3 = più importante)
    score: int           # contributo al PA score


# ─── PREVIOUS DAY HIGH / LOW ──────────────────────────────────────────────────

def get_previous_day_levels(df: pd.DataFrame) -> List[SRLevel]:
    """
    Previous Day High (PDH) e Previous Day Low (PDL).
    Livelli fondamentali in ICT/SMC: la liquidità del giorno precedente
    viene spesso 'sweepata' prima di un inversione o continuazione.
    """
    levels: List[SRLevel] = []
    try:
        df_t = df.copy()
        if 'time' in df_t.columns:
            df_t['_date'] = pd.to_datetime(df_t['time']).dt.date
        elif isinstance(df_t.index, pd.DatetimeIndex):
            df_t['_date'] = df_t.index.date
        else:
            return levels

        last_date  = df_t['_date'].iloc[-1]
        prev_mask  = df_t['_date'] < last_date
        if not prev_mask.any():
            return levels

        prev_data     = df_t[prev_mask]
        last_prev_day = prev_data['_date'].max()
        day_data      = prev_data[prev_data['_date'] == last_prev_day]
        if len(day_data) == 0:
            return levels

        pdh = float(day_data['high'].max())
        pdl = float(day_data['low'].min())

        levels.append(SRLevel(price=pdh, label="PDH", level_type="pdh", importance=3, score=20))
        levels.append(SRLevel(price=pdl, label="PDL", level_type="pdl", importance=3, score=20))

    except Exception:
        pass

    return levels


# ─── PREVIOUS WEEK HIGH / LOW ─────────────────────────────────────────────────

def get_previous_week_levels(df: pd.DataFrame) -> List[SRLevel]:
    """
    Previous Week High (PWH) e Previous Week Low (PWL).
    Livelli di timeframe superiore: molto spesso il mercato fa un fake-out
    sui PWH/PWL prima di invertire (classica trappola SMC).
    """
    levels: List[SRLevel] = []
    try:
        df_t = df.copy()
        if 'time' in df_t.columns:
            df_t['_dt'] = pd.to_datetime(df_t['time'])
        elif isinstance(df_t.index, pd.DatetimeIndex):
            df_t['_dt'] = df_t.index
        else:
            return levels

        df_t['_week'] = df_t['_dt'].dt.isocalendar().week.astype(int)
        df_t['_year'] = df_t['_dt'].dt.year

        last_week = int(df_t['_week'].iloc[-1])
        last_year = int(df_t['_year'].iloc[-1])

        cur_mask  = (df_t['_week'] == last_week) & (df_t['_year'] == last_year)
        prev_data = df_t[~cur_mask]
        if prev_data.empty:
            return levels

        last_pw = (
            prev_data[['_year', '_week']]
            .drop_duplicates()
            .sort_values(['_year', '_week'])
            .iloc[-1]
        )
        pw_data = prev_data[
            (prev_data['_year'] == last_pw['_year']) &
            (prev_data['_week'] == last_pw['_week'])
        ]
        if pw_data.empty:
            return levels

        pwh = float(pw_data['high'].max())
        pwl = float(pw_data['low'].min())

        levels.append(SRLevel(price=pwh, label="PWH", level_type="pwh", importance=3, score=15))
        levels.append(SRLevel(price=pwl, label="PWL", level_type="pwl", importance=3, score=15))

    except Exception:
        pass

    return levels


# ─── ROUND NUMBERS (LIVELLI PSICOLOGICI) ──────────────────────────────────────

def get_round_number_levels(price: float, symbol: str) -> List[SRLevel]:
    """
    Livelli psicologici tondi: zone dove si accumulano ordini di retail trader.
    In SMC vengono spesso usati come target di liquidity sweep.

    Default per simbolo:
      XAUUSD → ogni $50 e $100    (es: 2650, 2700, 2750, 2800)
      EURUSD → ogni 50 pip / 100 pip
      GBPUSD → ogni 50 pip / 100 pip
      USDJPY → ogni 0.50 e 1.00   (es: 150.00, 150.50)
    """
    levels: List[SRLevel] = []
    default_rounds = {
        "XAUUSD": [50.0, 100.0],
        "EURUSD": [0.005, 0.010],
        "GBPUSD": [0.005, 0.010],
        "USDJPY": [0.50, 1.00],
    }
    steps = getattr(config, 'PA_ROUND_LEVELS', default_rounds).get(symbol.upper(), [])
    if not steps:
        return levels

    seen: set = set()
    for idx, step in enumerate(steps):
        importance = 2 if idx == 1 else 1        # il livello più grande (es. $100) è più importante
        score      = 12 if importance == 2 else 8

        base = round(price / step) * step
        for mult in range(-4, 5):
            lvl = round(base + mult * step, 8)
            if abs(lvl - price) / max(abs(price), 1e-10) < 0.05:  # entro il 5% dal prezzo
                key = round(lvl, 6)
                if key not in seen and lvl > 0:
                    seen.add(key)
                    levels.append(SRLevel(
                        price=lvl,
                        label=f"Round {lvl:.5g}",
                        level_type="round",
                        importance=importance,
                        score=score,
                    ))

    return levels


# ─── SESSIONE ASIATICA HIGH / LOW ──────────────────────────────────────────────

def get_session_levels(df: pd.DataFrame, symbol: str) -> List[SRLevel]:
    """
    Asian Session High / Low: 00:00–04:00 ora broker.
    La sessione di Londra spesso 'runna' i massimi/minimi asiatici per prendere
    liquidità prima di invertire (classico ICT pattern).
    Particolarmente rilevante per USDJPY e GBPUSD.
    """
    levels: List[SRLevel] = []
    try:
        df_t = df.copy()
        if 'time' in df_t.columns:
            df_t['_dt'] = pd.to_datetime(df_t['time'])
        elif isinstance(df_t.index, pd.DatetimeIndex):
            df_t['_dt'] = df_t.index
        else:
            return levels

        df_t['_hour'] = df_t['_dt'].dt.hour
        df_t['_date'] = df_t['_dt'].dt.date

        last_date = df_t['_date'].iloc[-1]

        # Prova prima lo stesso giorno, poi il precedente
        for target_date in [last_date, (pd.to_datetime(last_date) - pd.Timedelta(days=1)).date()]:
            mask = (df_t['_hour'] >= 0) & (df_t['_hour'] < 4) & (df_t['_date'] == target_date)
            if mask.any():
                asian = df_t[mask]
                levels.append(SRLevel(
                    price=float(asian['high'].max()),
                    label="Asian High", level_type="session",
                    importance=2, score=12
                ))
                levels.append(SRLevel(
                    price=float(asian['low'].min()),
                    label="Asian Low", level_type="session",
                    importance=2, score=12
                ))
                break

    except Exception:
        pass

    return levels


# ─── ENTRY POINT PRINCIPALE ────────────────────────────────────────────────────

def find_nearby_levels(
    price: float,
    df: pd.DataFrame,
    symbol: str,
    atr: float,
    proximity_atr: float = 0.5,
) -> List[SRLevel]:
    """
    Raccoglie tutti i livelli S&R e filtra quelli vicini al prezzo corrente
    (entro proximity_atr × ATR).

    I livelli vengono ordinati per importanza decrescente così il più
    significativo appare per primo nella stringa reason del segnale.
    """
    proximity = atr * proximity_atr

    all_levels: List[SRLevel] = []
    all_levels.extend(get_previous_day_levels(df))
    all_levels.extend(get_previous_week_levels(df))
    all_levels.extend(get_round_number_levels(price, symbol))
    all_levels.extend(get_session_levels(df, symbol))

    nearby = [lv for lv in all_levels if abs(lv.price - price) <= proximity]
    nearby.sort(key=lambda x: x.importance, reverse=True)
    return nearby
