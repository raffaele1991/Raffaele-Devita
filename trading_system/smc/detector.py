"""
SMC Detector – punto di ingresso principale
=============================================
Combina structure + zones e produce un segnale SMC per ogni candela.
"""

import pandas as pd
import numpy as np
from dataclasses import dataclass
from typing import Optional
from .structure import detect_structure
from .zones import find_order_blocks, find_fvg, find_liquidity_levels
from trading_system import config
from trading_system.pa.detector import analyze_pa

# OB rilevanti solo se formati entro questi bar dalla candela corrente
OB_MAX_AGE_BARS = 80


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
    sl_adjusted: bool = False   # True se SL è stato spostato oltre una liq zone
    # Price Action (popolati dal modulo PA)
    pa_pattern: str = ""        # es. "Pin Bar Bull", "Engulfing Bear + Doji"
    pa_score: int   = 0         # score PA composito 0-100
    pa_near_level: str = ""     # es. "PDH", "Round 2700", "Asian Low"


class SMCDetector:
    """
    Analizza un DataFrame OHLCV e restituisce un segnale SMC se presente.
    Il segnale richiede:
      1. Trend confermato (BOS / CHoCH)
      2. Prezzo ritorna su un Order Block attivo
      3. SL/TP basati su ATR (allineati con le label del modello ML)
      4. (Bonus) FVG nella zona impulso vicino all'OB
      5. (Bonus) Sweep di liquidità prima dell'inversione
    """

    def __init__(self, symbol: str):
        self.symbol = symbol

    def _adjust_sl_for_liquidity(
        self,
        entry: float,
        sl_raw: float,
        direction: str,
        liq_levels,
        atr: float,
    ) -> tuple[float, bool]:
        """
        Sposta lo SL oltre una liquidity zone se lo SL grezzo ci cade dentro.

        SHORT: SL è sopra entry → cerca liq "highs" tra entry e sl_raw + search_range
               → porta SL sopra il livello più alto trovato + buffer
        LONG:  SL è sotto entry → cerca liq "lows"  tra sl_raw - search_range e entry
               → porta SL sotto il livello più basso trovato - buffer

        Ritorna (sl_aggiustato, adjusted_flag).
        Se il nuovo SL supera ATR * SL_MAX_MULTIPLIER ritorna (None, False)
        per segnalare che il trade va skippato (R:R troppo stretto).
        """
        buffer       = config.SL_LIQ_BUFFER_PIPS.get(self.symbol, 0.0005)
        search_range = atr * config.SL_LIQ_SEARCH_ATR
        max_sl_dist  = atr * config.SL_MAX_MULTIPLIER

        if direction == "short":
            # Cerca equal-highs zone tra entry e sl_raw + search_range
            candidates = [
                lv.price for lv in liq_levels
                if lv.direction == "highs"
                and entry < lv.price <= sl_raw + search_range
            ]
            if candidates:
                sl_new = max(candidates) + buffer
                if (sl_new - entry) > max_sl_dist:
                    return None, False          # SL troppo largo → skip trade
                return sl_new, True

        else:  # long
            # Cerca equal-lows zone tra sl_raw - search_range e entry
            candidates = [
                lv.price for lv in liq_levels
                if lv.direction == "lows"
                and sl_raw - search_range <= lv.price < entry
            ]
            if candidates:
                sl_new = min(candidates) - buffer
                if sl_new <= 0 or (entry - sl_new) > max_sl_dist:
                    return None, False          # SL troppo largo → skip trade
                return sl_new, True

        return sl_raw, False                    # nessuna zona trovata → SL invariato

    def analyze(self, df: pd.DataFrame, return_struct: bool = False):
        """
        df: DataFrame con colonne open, high, low, close, volume
            ordinato dal più vecchio al più recente.
        Ritorna SMCSignal se c'è un setup valido sull'ultima candela, None altrimenti.
        """
        if len(df) < 60:
            return (None, None) if return_struct else None

        df = detect_structure(df)
        order_blocks = find_order_blocks(df, self.symbol)
        fvgs         = find_fvg(df, self.symbol)
        liq_levels   = find_liquidity_levels(df, self.symbol)

        last      = df.iloc[-1]
        last_idx  = len(df) - 1
        trend     = last["trend"]   # 1 bullish, -1 bearish, 0 undefined

        if trend == 0:
            return (None, df) if return_struct else None

        current_price = last["close"]
        last_low  = last["low"]
        last_high = last["high"]

        # ATR per sizing di SL/TP e tolleranze di prossimità
        tr = pd.concat([
            df["high"] - df["low"],
            (df["high"] - df["close"].shift(1)).abs(),
            (df["low"]  - df["close"].shift(1)).abs(),
        ], axis=1).max(axis=1)
        atr = tr.rolling(14).mean().iloc[-1]
        if pd.isna(atr) or atr <= 0:
            atr = (df["high"] - df["low"]).mean()

        # SL/TP basati su ATR – identici alla logica di build_labels in features.py
        # Questo garantisce che le previsioni del modello ML corrispondano
        # esattamente agli esiti reali simulati dal backtest.
        sl_dist = atr * config.ATR_SL_MULTIPLIER
        tp_dist = sl_dist * config.MIN_RISK_REWARD

        # ── LONG SETUP ─────────────────────────────────────────────────────
        if trend == 1:
            # Bullish OB valido se:
            # - OB recente (max OB_MAX_AGE_BARS bar fa)
            # - il LOW è entro 0.5 ATR dal top dell'OB (tocco o avvicinamento ravvicinato)
            # - il CLOSE è sopra il fondo dell'OB (rimbalzo confermato)
            active_bull_obs = [
                ob for ob in order_blocks
                if ob.direction == "bullish"
                and ob.active
                and (last_idx - ob.index) <= OB_MAX_AGE_BARS
                and last_low  <= ob.top + atr * 0.5   # max 0.5 ATR sopra il top OB
                and current_price >= ob.bottom         # close sopra il fondo OB
            ]
            # Più recente prima
            active_bull_obs.sort(key=lambda x: x.index, reverse=True)

            for ob in active_bull_obs:
                # FVG bullish nella zona impulso: compresa tra (ob.bottom - 1 ATR)
                # e (ob.top + 3 ATR) — il FVG è tipicamente nell'impulso sopra l'OB
                fvg_in_zone = next(
                    (f for f in fvgs
                     if f.direction == "bullish"
                     and not f.filled
                     and f.index < last_idx
                     and f.bottom >= ob.bottom - atr
                     and f.top    <= ob.top + 3 * atr),
                    None
                )

                # Liquidity sweep: prezzo ha preso i lows prima di rimbalzare?
                liq_swept = any(
                    lv.direction == "lows"
                    and abs(lv.price - ob.bottom) <= atr
                    for lv in liq_levels
                )

                entry    = current_price
                sl_raw   = entry - sl_dist  # SL grezzo ATR-based

                # Aggiusta SL se cade dentro una liquidity zone (stop hunt protection)
                sl, sl_adj = self._adjust_sl_for_liquidity(
                    entry, sl_raw, "long", liq_levels, atr
                )
                if sl is None:
                    continue  # SL troppo largo dopo aggiustamento → skip

                sl_dist_actual = entry - sl
                tp = entry + sl_dist_actual * config.MIN_RISK_REWARD

                if sl <= 0 or tp <= 0:
                    continue

                # ── Price Action analysis ───────────────────────────────────
                pa_sig = None
                if getattr(config, 'PA_ENABLED', True):
                    try:
                        pa_sig = analyze_pa(df, self.symbol, direction_hint="long", atr=atr)
                        pa_min = getattr(config, 'PA_MIN_SCORE', 0)
                        if pa_min > 0 and pa_sig.score < pa_min:
                            continue  # PA non confermata → prova prossimo OB
                    except Exception:
                        pa_sig = None

                reason_parts = ["Bullish OB in uptrend"]
                if fvg_in_zone:
                    reason_parts.append("FVG confluence")
                if liq_swept:
                    reason_parts.append("Liquidity swept")
                if sl_adj:
                    reason_parts.append("SL beyond liq zone")
                if pa_sig and pa_sig.pattern_names:
                    reason_parts.append(f"PA: {pa_sig.pattern_names}")
                if pa_sig and pa_sig.level_names:
                    reason_parts.append(f"@ {pa_sig.level_names}")

                sig = SMCSignal(
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
                    sl_adjusted=sl_adj,
                    pa_pattern=pa_sig.pattern_names if pa_sig else "",
                    pa_score=pa_sig.score if pa_sig else 0,
                    pa_near_level=pa_sig.level_names if pa_sig else "",
                )
                return (sig, df) if return_struct else sig

        # ── SHORT SETUP ────────────────────────────────────────────────────
        if trend == -1:
            # Bearish OB valido se:
            # - OB recente (max OB_MAX_AGE_BARS bar fa)
            # - l'HIGH è entro 0.5 ATR dal fondo dell'OB
            # - il CLOSE è sotto il top dell'OB (distribuzione)
            active_bear_obs = [
                ob for ob in order_blocks
                if ob.direction == "bearish"
                and ob.active
                and (last_idx - ob.index) <= OB_MAX_AGE_BARS
                and last_high >= ob.bottom - atr * 0.5  # max 0.5 ATR sotto il fondo OB
                and current_price <= ob.top              # close sotto il top OB
            ]
            active_bear_obs.sort(key=lambda x: x.index, reverse=True)

            for ob in active_bear_obs:
                fvg_in_zone = next(
                    (f for f in fvgs
                     if f.direction == "bearish"
                     and not f.filled
                     and f.index < last_idx
                     and f.top    <= ob.top + atr
                     and f.bottom >= ob.bottom - 3 * atr),
                    None
                )

                liq_swept = any(
                    lv.direction == "highs"
                    and abs(lv.price - ob.top) <= atr
                    for lv in liq_levels
                )

                entry    = current_price
                sl_raw   = entry + sl_dist  # SL grezzo ATR-based

                # Aggiusta SL se cade dentro una liquidity zone (stop hunt protection)
                sl, sl_adj = self._adjust_sl_for_liquidity(
                    entry, sl_raw, "short", liq_levels, atr
                )
                if sl is None:
                    continue  # SL troppo largo dopo aggiustamento → skip

                sl_dist_actual = sl - entry
                tp = entry - sl_dist_actual * config.MIN_RISK_REWARD

                if sl <= 0 or tp <= 0:
                    continue

                # ── Price Action analysis ───────────────────────────────────
                pa_sig = None
                if getattr(config, 'PA_ENABLED', True):
                    try:
                        pa_sig = analyze_pa(df, self.symbol, direction_hint="short", atr=atr)
                        pa_min = getattr(config, 'PA_MIN_SCORE', 0)
                        if pa_min > 0 and pa_sig.score < pa_min:
                            continue  # PA non confermata → prova prossimo OB
                    except Exception:
                        pa_sig = None

                reason_parts = ["Bearish OB in downtrend"]
                if fvg_in_zone:
                    reason_parts.append("FVG confluence")
                if liq_swept:
                    reason_parts.append("Liquidity swept")
                if sl_adj:
                    reason_parts.append("SL beyond liq zone")
                if pa_sig and pa_sig.pattern_names:
                    reason_parts.append(f"PA: {pa_sig.pattern_names}")
                if pa_sig and pa_sig.level_names:
                    reason_parts.append(f"@ {pa_sig.level_names}")

                sig = SMCSignal(
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
                    sl_adjusted=sl_adj,
                    pa_pattern=pa_sig.pattern_names if pa_sig else "",
                    pa_score=pa_sig.score if pa_sig else 0,
                    pa_near_level=pa_sig.level_names if pa_sig else "",
                )
                return (sig, df) if return_struct else sig

        return (None, df) if return_struct else None
