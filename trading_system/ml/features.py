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
    df["trend_num"]    = df.get("trend", pd.Series(0, index=df.index))
    df["bos_bull_n"]   = df.get("bos_bull",   pd.Series(False, index=df.index)).astype(int)
    df["bos_bear_n"]   = df.get("bos_bear",   pd.Series(False, index=df.index)).astype(int)
    df["choch_bull_n"] = df.get("choch_bull", pd.Series(False, index=df.index)).astype(int)
    df["choch_bear_n"] = df.get("choch_bear", pd.Series(False, index=df.index)).astype(int)

    # Quante candele fa è stato l'ultimo BOS
    bos_events = (df["bos_bull_n"] | df["bos_bear_n"] | df["choch_bull_n"] | df["choch_bear_n"]).astype(bool)
    df["bars_since_structure"] = bos_events[::-1].cumsum()[::-1].where(bos_events, 0)

    return df


def add_smc_signal_features(df: pd.DataFrame, symbol: str = "XAUUSD") -> pd.DataFrame:
    """
    Feature SMC-specifiche basate su Order Block, FVG e liquidità.
    Queste feature codificano direttamente la qualità del setup SMC e sono
    il vero discriminatore tra trade vincenti e perdenti.

    Richiede detect_structure() già eseguito (colonne bos_bull, trend, ecc.)
    e add_volatility() già eseguito (colonna atr).
    """
    from trading_system.smc.zones import find_order_blocks, find_fvg, find_liquidity_levels

    df = df.copy()
    n = len(df)

    # Rileva zone SMC sull'intero DataFrame
    order_blocks = find_order_blocks(df, symbol)
    fvgs         = find_fvg(df, symbol)
    liq_levels   = find_liquidity_levels(df, symbol)

    # Separa per direzione per lookup rapido
    bull_obs  = [ob for ob in order_blocks if ob.direction == "bullish"]
    bear_obs  = [ob for ob in order_blocks if ob.direction == "bearish"]
    bull_fvgs = [f for f in fvgs if f.direction == "bullish"]
    bear_fvgs = [f for f in fvgs if f.direction == "bearish"]
    liq_highs = [lv for lv in liq_levels if lv.direction == "highs"]
    liq_lows  = [lv for lv in liq_levels if lv.direction == "lows"]

    OB_MAX_AGE = 80

    # Arrays da riempire
    ob_age_norm    = np.zeros(n)
    ob_size_atr    = np.zeros(n)
    ob_penetration = np.zeros(n)
    ob_has_fvg     = np.zeros(n)
    fvg_size_atr   = np.zeros(n)
    liq_swept_arr  = np.zeros(n)
    dist_to_liq    = np.full(n, 10.0)
    ob_count_zone  = np.zeros(n)
    is_choch_arr   = np.zeros(n)

    # is_choch: l'evento di struttura più recente era un CHoCH?  (O(n) vettorizzato)
    choch_bull = df.get("choch_bull", pd.Series(False, index=df.index)).values.astype(bool)
    choch_bear = df.get("choch_bear", pd.Series(False, index=df.index)).values.astype(bool)
    bos_bull   = df.get("bos_bull",   pd.Series(False, index=df.index)).values.astype(bool)
    bos_bear   = df.get("bos_bear",   pd.Series(False, index=df.index)).values.astype(bool)

    any_struct    = choch_bull | choch_bear | bos_bull | bos_bear
    is_choch_evt  = choch_bull | choch_bear
    current_choch = 0
    for i in range(n):
        if any_struct[i]:
            current_choch = 1 if is_choch_evt[i] else 0
        is_choch_arr[i] = current_choch

    # Estrai array numpy per accesso rapido
    trend_vals = df.get("trend_num", df.get("trend", pd.Series(0, index=df.index))).values
    atr_vals   = df["atr"].values if "atr" in df.columns else np.ones(n)
    close_vals = df["close"].values
    high_vals  = df["high"].values
    low_vals   = df["low"].values

    for i in range(n):
        t = trend_vals[i]
        if t == 0:
            continue

        a = atr_vals[i]
        if np.isnan(a) or a <= 0:
            continue

        c = close_vals[i]
        h = high_vals[i]
        l = low_vals[i]

        # ── Trova il miglior OB per questo bar ───────────────────────────────
        obs = bull_obs if t == 1 else bear_obs
        best_ob = None
        for ob in reversed(obs):
            age = i - ob.index
            if age <= 0 or age > OB_MAX_AGE:
                continue
            # L'OB è "attivo" al bar i se non è ancora stato invalidato
            if ob.invalidated_at != -1 and ob.invalidated_at <= i:
                continue
            if t == 1 and l <= ob.top + a and c >= ob.bottom:
                best_ob = ob
                break
            elif t == -1 and h >= ob.bottom - a and c <= ob.top:
                best_ob = ob
                break

        if best_ob is None:
            continue

        ob_sz = max(best_ob.top - best_ob.bottom, a * 0.01)  # evita div/0

        ob_age_norm[i] = (i - best_ob.index) / OB_MAX_AGE
        ob_size_atr[i] = ob_sz / a

        # Penetrazione: 0 = al bordo dell'OB (entry ideale), 1 = al fondo
        if t == 1:
            ob_penetration[i] = max(0.0, min(1.0, (best_ob.top - c) / ob_sz))
        else:
            ob_penetration[i] = max(0.0, min(1.0, (c - best_ob.bottom) / ob_sz))

        # ── FVG confluente nella zona dell'impulso (OB ± 3 ATR) ─────────────
        # In SMC il FVG è creato dall'impulso che ha generato l'OB, quindi
        # si trova sopra/sotto l'OB ma nella stessa area di prezzo (±3 ATR)
        fvgs_dir = bull_fvgs if t == 1 else bear_fvgs
        zone_lo = best_ob.bottom - 3 * a
        zone_hi = best_ob.top    + 3 * a
        for fvg in reversed(fvgs_dir):
            if fvg.index >= i:
                continue
            if fvg.filled_at != -1 and fvg.filled_at <= i:
                continue
            # FVG deve trovarsi nella zona dell'OB (dentro ±3 ATR)
            if fvg.bottom >= zone_lo and fvg.top <= zone_hi:
                ob_has_fvg[i]   = 1.0
                fvg_size_atr[i] = fvg.size / a
                break

        # ── Sweep di liquidità prima dell'entry (entro 1 ATR dall'OB) ─────────
        if t == 1:
            for lv in liq_lows:
                if abs(lv.price - best_ob.bottom) <= a:
                    liq_swept_arr[i] = 1.0
                    break
        else:
            for lv in liq_highs:
                if abs(lv.price - best_ob.top) <= a:
                    liq_swept_arr[i] = 1.0
                    break

        # ── Distanza alla liquidità obiettivo (TP naturale) ───────────────────
        min_d = 10.0
        if t == 1:
            for lv in liq_highs:
                d = (lv.price - c) / a
                if 0 < d < min_d:
                    min_d = d
        else:
            for lv in liq_lows:
                d = (c - lv.price) / a
                if 0 < d < min_d:
                    min_d = d
        dist_to_liq[i] = min_d

        # ── OB sovrapposti nella stessa zona (confluenza) ─────────────────────
        count = 0
        for other in obs:
            age2 = i - other.index
            if age2 <= 0 or age2 > OB_MAX_AGE:
                continue
            if other.invalidated_at != -1 and other.invalidated_at <= i:
                continue
            overlap2 = min(other.top, best_ob.top) - max(other.bottom, best_ob.bottom)
            if overlap2 > 0:
                count += 1
        ob_count_zone[i] = min(float(count), 5.0)

    df["ob_age_norm"]    = ob_age_norm
    df["ob_size_atr"]    = ob_size_atr
    df["ob_penetration"] = ob_penetration
    df["ob_has_fvg"]     = ob_has_fvg
    df["fvg_size_atr"]   = fvg_size_atr
    df["liq_swept_smc"]  = liq_swept_arr
    df["dist_to_liq_atr"] = dist_to_liq
    df["ob_count_zone"]  = ob_count_zone
    df["is_choch"]       = is_choch_arr

    return df


def build_features(df: pd.DataFrame, symbol: str = "XAUUSD") -> pd.DataFrame:
    """Pipeline completa di feature engineering."""
    df = add_candle_features(df)
    df = add_moving_averages(df)
    df = add_volatility(df)
    df = add_momentum(df)
    df = add_smc_features(df)
    df = add_smc_signal_features(df, symbol=symbol)
    df = df.dropna()
    return df


FEATURE_COLUMNS = [
    # ── CANDELA & RENDIMENTI ──────────────────────────────────────────────────
    "body_pct", "upper_shadow", "lower_shadow", "is_bullish",
    "ret_1", "ret_3", "ret_5", "ret_10", "ret_20",
    # ── EMA DISTANCE (contesto macro) ────────────────────────────────────────
    "close_vs_ema_9", "close_vs_ema_21", "close_vs_ema_50",
    "close_vs_ema_100", "close_vs_ema_200",
    # ── VOLATILITÀ ────────────────────────────────────────────────────────────
    "atr_pct", "vol_5", "vol_20",
    # ── MOMENTUM (contesto) ───────────────────────────────────────────────────
    "rsi_norm", "macd_norm", "macd_hist", "stoch_k", "stoch_d",
    # ── SMC STRUTTURA (generali) ─────────────────────────────────────────────
    "trend_num", "bos_bull_n", "bos_bear_n", "choch_bull_n", "choch_bear_n",
    "bars_since_structure",
    # ── SMC SEGNALE (qualità setup — i discriminatori più importanti) ─────────
    "ob_age_norm",      # freschezza OB: 0=appena formato, 1=vecchio 80 bar
    "ob_size_atr",      # dimensione OB in unità ATR
    "ob_penetration",   # profondità entry: 0=bordo ideale, 1=fondo OB
    "ob_has_fvg",       # 1 se c'è FVG confluente nella zona OB (±3 ATR)
    "fvg_size_atr",     # dimensione FVG in ATR (0 se assente)
    "dist_to_liq_atr",  # distanza alla prossima liquidità obiettivo (ATR)
    "ob_count_zone",    # OB sovrapposti nella zona (0-5)
    "is_choch",         # 1=CHoCH (inversione), 0=BOS (continuazione)
]


def build_labels(df: pd.DataFrame, lookahead: int = 10, min_move_atr: float = 1.0) -> pd.Series:
    """
    Label binaria: 1 se il trade nella direzione del trend era vincente.
    Un trade è vincente se il TP viene colpito PRIMA dello SL entro `lookahead` candele.

    Usa controllo sequenziale bar-per-bar (lo stesso dell'engine di backtest) per
    evitare falsi negativi dovuti a SL colpiti dopo il TP nella stessa finestra.
    SL/TP sono calcolati con ATR identicamente al detector.py.
    """
    labels = pd.Series(0, index=df.index)
    atr   = df["atr"].values
    trend = df["trend_num"].values
    close = df["close"].values
    high  = df["high"].values
    low   = df["low"].values

    for i in range(len(df) - lookahead):
        t = trend[i]
        if t == 0:
            continue

        a = atr[i]
        if np.isnan(a) or a <= 0:
            continue

        sl_dist = a * config.ATR_SL_MULTIPLIER
        entry   = close[i]

        if t == 1:  # long
            sl = entry - sl_dist
            tp = entry + sl_dist * config.MIN_RISK_REWARD
            # Controllo sequenziale: il primo livello colpito determina l'esito
            for k in range(i + 1, i + lookahead + 1):
                sl_hit = low[k]  <= sl
                tp_hit = high[k] >= tp
                if sl_hit and tp_hit:
                    # Entrambi nella stessa candela: usa la direzione della candela
                    labels.iloc[i] = 1 if close[k] >= close[k - 1] else 0
                    break
                elif sl_hit:
                    labels.iloc[i] = 0
                    break
                elif tp_hit:
                    labels.iloc[i] = 1
                    break

        else:  # short
            sl = entry + sl_dist
            tp = entry - sl_dist * config.MIN_RISK_REWARD
            for k in range(i + 1, i + lookahead + 1):
                sl_hit = high[k] >= sl
                tp_hit = low[k]  <= tp
                if sl_hit and tp_hit:
                    labels.iloc[i] = 1 if close[k] <= close[k - 1] else 0
                    break
                elif sl_hit:
                    labels.iloc[i] = 0
                    break
                elif tp_hit:
                    labels.iloc[i] = 1
                    break

    return labels
