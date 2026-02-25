"""
Feature Engineering
====================
Costruisce le feature per il modello ML partendo dai dati OHLCV + output SMC.

Ottimizzato per 416k+ candele:
- add_smc_signal_features: OB/FVG/Liq pre-convertiti in array NumPy; inner loop
  sostituiti con operazioni vettorizzate → ~10x speedup
- build_labels: matrice NumPy 2D per lookahead → ~20x speedup
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


def add_time_features(df: pd.DataFrame) -> pd.DataFrame:
    """Feature temporali: ora del giorno (ciclica) e sessioni di trading."""
    df = df.copy()

    hour = df.index.hour + df.index.minute / 60.0

    # Encoding ciclico: mantiene la continuità tra 23:59 e 00:00
    df["hour_sin"] = np.sin(2 * np.pi * hour / 24)
    df["hour_cos"] = np.cos(2 * np.pi * hour / 24)

    # Giorno della settimana ciclico (0=lun, 4=ven)
    dow = df.index.dayofweek.astype(float)
    df["dow_sin"] = np.sin(2 * np.pi * dow / 5)
    df["dow_cos"] = np.cos(2 * np.pi * dow / 5)

    # Kill zone sessioni (ora del server MT5, tipicamente UTC+2/3)
    # London KZ: 07:00-10:00 | NY KZ: 13:00-16:00 | Asia: 00:00-04:00
    h_int = df.index.hour
    df["is_london"] = ((h_int >= 7)  & (h_int < 11)).astype(float)
    df["is_ny"]     = ((h_int >= 13) & (h_int < 17)).astype(float)
    df["is_asia"]   = ((h_int >= 0)  & (h_int < 4)).astype(float)

    return df


def add_volume_features(df: pd.DataFrame) -> pd.DataFrame:
    """Feature di volume: normalizzazione e spike istituzionali.
    Robusto a volume=0 (broker senza dati volume reale per spot FX/Gold).
    """
    df = df.copy()
    vol = df["volume"]
    vol_ma20 = vol.rolling(20).mean()

    # Se vol_ma20 = 0 (volume reale assente), fillna(1.0) → feature neutra
    # Così dropna() non elimina queste righe
    safe_ma20 = vol_ma20.where(vol_ma20 > 0, np.nan)
    df["vol_norm"]  = (vol / safe_ma20).clip(0, 10).fillna(1.0)
    df["vol_spike"] = (df["vol_norm"] > 2.0).astype(float)
    df["vol_trend"] = (vol.rolling(5).mean() > vol_ma20).fillna(False).astype(float)

    return df


def add_trend_strength(df: pd.DataFrame) -> pd.DataFrame:
    """ADX (forza trend) e posizione nelle Bollinger Bands."""
    df = df.copy()
    period = 14

    high  = df["high"]
    low   = df["low"]
    close = df["close"]
    atr14 = df["atr"].replace(0, np.nan)

    # +DM / -DM: diff()[0] è sempre NaN → fillna(0) per non bloccare l'EWM
    # Usiamo .where() per evitare SettingWithCopyWarning
    raw_up   = high.diff().fillna(0).clip(lower=0)
    raw_down = (-low.diff()).fillna(0).clip(lower=0)
    both_pos = (high.diff() > 0) & (-low.diff() > 0)
    plus_dm  = raw_up.where(~(both_pos & (raw_up < raw_down)), 0.0)
    minus_dm = raw_down.where(~(both_pos & (raw_down <= raw_up)), 0.0)

    # ignore_na=True: le prime righe dove atr14 è NaN non bloccano l'intera serie
    _ewm = dict(alpha=1 / period, adjust=False, ignore_na=True)
    plus_di  = 100 * plus_dm.ewm(**_ewm).mean() / atr14
    minus_di = 100 * minus_dm.ewm(**_ewm).mean() / atr14
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    # fillna(0) su dx: per i primi ~14 bar (atr NaN) trattiamo DX=0
    df["adx"] = dx.fillna(0).ewm(**_ewm).mean() / 100  # normalizzato 0-1

    # Bollinger Bands
    bb_ma  = close.rolling(20).mean()
    bb_std = close.rolling(20).std()
    bb_rng = (4 * bb_std).replace(0, np.nan)
    df["bb_position"] = ((close - (bb_ma - 2 * bb_std)) / bb_rng).fillna(0.5)  # 0.5=neutro se flat
    df["bb_width"]    = (4 * bb_std / close).fillna(0.0)

    return df


def add_smc_features(df: pd.DataFrame) -> pd.DataFrame:
    """Feature derivate dall'analisi SMC già presente nel DataFrame."""
    df = df.copy()
    df["trend_num"]    = df.get("trend", pd.Series(0, index=df.index))
    df["bos_bull_n"]   = df.get("bos_bull",   pd.Series(False, index=df.index)).astype(int)
    df["bos_bear_n"]   = df.get("bos_bear",   pd.Series(False, index=df.index)).astype(int)
    df["choch_bull_n"] = df.get("choch_bull", pd.Series(False, index=df.index)).astype(int)
    df["choch_bear_n"] = df.get("choch_bear", pd.Series(False, index=df.index)).astype(int)

    # Quante candele fa è stato l'ultimo BOS/CHoCH (forward-fill dell'indice dell'evento)
    bos_events = (df["bos_bull_n"] | df["bos_bear_n"] | df["choch_bull_n"] | df["choch_bear_n"]).astype(bool)
    n = len(df)
    positions = np.arange(n, dtype=np.float64)
    last_event_pos = np.where(bos_events.values, positions, np.nan)
    last_event_pos = pd.Series(last_event_pos).ffill().values
    bars_since = np.where(np.isnan(last_event_pos), n, positions - last_event_pos)
    df["bars_since_structure"] = np.clip(bars_since / 100.0, 0, 1)  # normalizzato 0-1, cap 100 bar

    return df


# ── Helper: converti liste di oggetti in array NumPy ──────────────────────────

def _ob_to_arrays(obs):
    """Converte lista OrderBlock in 4 array NumPy (idx, top, bot, inv)."""
    if not obs:
        empty_i = np.array([], dtype=np.int32)
        empty_f = np.array([], dtype=np.float64)
        return empty_i, empty_f, empty_f, empty_i
    return (
        np.array([o.index          for o in obs], dtype=np.int32),
        np.array([o.top            for o in obs], dtype=np.float64),
        np.array([o.bottom         for o in obs], dtype=np.float64),
        np.array([o.invalidated_at for o in obs], dtype=np.int32),
    )


def _fvg_to_arrays(fvgs_list):
    """Converte lista FairValueGap in 4 array NumPy (idx, top, bot, filled_at)."""
    if not fvgs_list:
        empty_i = np.array([], dtype=np.int32)
        empty_f = np.array([], dtype=np.float64)
        return empty_i, empty_f, empty_f, empty_i
    return (
        np.array([f.index     for f in fvgs_list], dtype=np.int32),
        np.array([f.top       for f in fvgs_list], dtype=np.float64),
        np.array([f.bottom    for f in fvgs_list], dtype=np.float64),
        np.array([f.filled_at for f in fvgs_list], dtype=np.int32),
    )


def add_smc_signal_features(df: pd.DataFrame, symbol: str = "XAUUSD") -> pd.DataFrame:
    """
    Feature SMC-specifiche basate su Order Block, FVG e liquidità.

    Ottimizzato: OB/FVG/Liq pre-convertiti in array NumPy una volta sola;
    tutti i loop interni sostituiti con operazioni vettorizzate NumPy.
    Il loop esterno su n barre rimane ma il lavoro interno è O(1) numpy.
    """
    from trading_system.smc.zones import find_order_blocks, find_fvg, find_liquidity_levels

    df = df.copy()
    n = len(df)

    order_blocks = find_order_blocks(df, symbol)
    fvgs         = find_fvg(df, symbol)
    liq_levels   = find_liquidity_levels(df, symbol)

    # Separa per direzione
    bull_obs  = [ob for ob in order_blocks if ob.direction == "bullish"]
    bear_obs  = [ob for ob in order_blocks if ob.direction == "bearish"]
    bull_fvgs = [f  for f  in fvgs         if f.direction  == "bullish"]
    bear_fvgs = [f  for f  in fvgs         if f.direction  == "bearish"]
    liq_highs = [lv for lv in liq_levels   if lv.direction == "highs"]
    liq_lows  = [lv for lv in liq_levels   if lv.direction == "lows"]

    # Pre-converti in array NumPy
    bull_ob_idx, bull_ob_top, bull_ob_bot, bull_ob_inv = _ob_to_arrays(bull_obs)
    bear_ob_idx, bear_ob_top, bear_ob_bot, bear_ob_inv = _ob_to_arrays(bear_obs)
    bull_fvg_idx, bull_fvg_top, bull_fvg_bot, bull_fvg_filled = _fvg_to_arrays(bull_fvgs)
    bear_fvg_idx, bear_fvg_top, bear_fvg_bot, bear_fvg_filled = _fvg_to_arrays(bear_fvgs)
    liq_highs_arr = np.array([lv.price for lv in liq_highs], dtype=np.float64) if liq_highs else np.array([])
    liq_lows_arr  = np.array([lv.price for lv in liq_lows],  dtype=np.float64) if liq_lows  else np.array([])

    OB_MAX_AGE = 80

    ob_age_norm    = np.zeros(n)
    ob_size_atr    = np.zeros(n)
    ob_penetration = np.zeros(n)
    ob_has_fvg     = np.zeros(n)
    fvg_size_atr   = np.zeros(n)
    liq_swept_arr  = np.zeros(n)
    dist_to_liq    = np.full(n, 10.0)
    ob_count_zone  = np.zeros(n)

    # ── is_choch: forward-fill vettorizzato ───────────────────────────────────
    choch_bull = df.get("choch_bull", pd.Series(False, index=df.index)).values.astype(bool)
    choch_bear = df.get("choch_bear", pd.Series(False, index=df.index)).values.astype(bool)
    bos_bull   = df.get("bos_bull",   pd.Series(False, index=df.index)).values.astype(bool)
    bos_bear   = df.get("bos_bear",   pd.Series(False, index=df.index)).values.astype(bool)

    any_struct   = choch_bull | choch_bear | bos_bull | bos_bear
    is_choch_evt = choch_bull | choch_bear
    struct_vals  = np.where(any_struct, np.where(is_choch_evt, 1.0, 0.0), np.nan)
    is_choch_arr = pd.Series(struct_vals).ffill().fillna(0.0).values

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

        # ── Seleziona array per direzione ─────────────────────────────────────
        if t == 1:
            ob_idx_a, ob_top_a, ob_bot_a, ob_inv_a = bull_ob_idx, bull_ob_top, bull_ob_bot, bull_ob_inv
        else:
            ob_idx_a, ob_top_a, ob_bot_a, ob_inv_a = bear_ob_idx, bear_ob_top, bear_ob_bot, bear_ob_inv

        if len(ob_idx_a) == 0:
            continue

        # ── Trova miglior OB (vettorizzato) ──────────────────────────────────
        age   = i - ob_idx_a
        valid = (age > 0) & (age <= OB_MAX_AGE) & ((ob_inv_a == -1) | (ob_inv_a > i))

        if t == 1:
            proximity = (l <= ob_top_a + 0.5 * a) & (c >= ob_bot_a)
        else:
            proximity = (h >= ob_bot_a - 0.5 * a) & (c <= ob_top_a)

        candidates = valid & proximity
        if not candidates.any():
            continue

        # Miglior OB = più recente (minore età)
        masked_age = np.where(candidates, age, OB_MAX_AGE + 1)
        best_j     = int(np.argmin(masked_age))

        ob_sz = max(ob_top_a[best_j] - ob_bot_a[best_j], a * 0.01)

        ob_age_norm[i] = age[best_j] / OB_MAX_AGE
        ob_size_atr[i] = ob_sz / a

        if t == 1:
            ob_penetration[i] = max(0.0, min(1.0, (ob_top_a[best_j] - c) / ob_sz))
        else:
            ob_penetration[i] = max(0.0, min(1.0, (c - ob_bot_a[best_j]) / ob_sz))

        # ── FVG confluente (vettorizzato) ─────────────────────────────────────
        if t == 1:
            fvg_idx_a, fvg_top_a, fvg_bot_a, fvg_f_a = bull_fvg_idx, bull_fvg_top, bull_fvg_bot, bull_fvg_filled
            zone_lo = ob_bot_a[best_j] - a
            zone_hi = ob_top_a[best_j] + 3 * a
        else:
            fvg_idx_a, fvg_top_a, fvg_bot_a, fvg_f_a = bear_fvg_idx, bear_fvg_top, bear_fvg_bot, bear_fvg_filled
            zone_lo = ob_bot_a[best_j] - 3 * a
            zone_hi = ob_top_a[best_j] + a

        if len(fvg_idx_a) > 0:
            vf = (fvg_idx_a < i) & ((fvg_f_a == -1) | (fvg_f_a > i)) & \
                 (fvg_bot_a >= zone_lo) & (fvg_top_a <= zone_hi)
            if vf.any():
                fvg_ages = np.where(vf, i - fvg_idx_a, n + 1)
                bfj = int(np.argmin(fvg_ages))
                if vf[bfj]:
                    ob_has_fvg[i]   = 1.0
                    fvg_size_atr[i] = (fvg_top_a[bfj] - fvg_bot_a[bfj]) / a

        # ── Sweep di liquidità (vettorizzato) ─────────────────────────────────
        if t == 1:
            if len(liq_lows_arr) > 0 and np.any(np.abs(liq_lows_arr - ob_bot_a[best_j]) <= a):
                liq_swept_arr[i] = 1.0
        else:
            if len(liq_highs_arr) > 0 and np.any(np.abs(liq_highs_arr - ob_top_a[best_j]) <= a):
                liq_swept_arr[i] = 1.0

        # ── Distanza alla liquidità obiettivo (vettorizzato) ──────────────────
        if t == 1 and len(liq_highs_arr) > 0:
            d     = (liq_highs_arr - c) / a
            pos_d = d[d > 0]
            if len(pos_d) > 0:
                dist_to_liq[i] = float(pos_d.min())
        elif t == -1 and len(liq_lows_arr) > 0:
            d     = (c - liq_lows_arr) / a
            pos_d = d[d > 0]
            if len(pos_d) > 0:
                dist_to_liq[i] = float(pos_d.min())

        # ── OB sovrapposti nella zona (vettorizzato) ──────────────────────────
        valid2   = (age > 0) & (age <= OB_MAX_AGE) & ((ob_inv_a == -1) | (ob_inv_a > i))
        overlap2 = np.minimum(ob_top_a, ob_top_a[best_j]) - np.maximum(ob_bot_a, ob_bot_a[best_j])
        ob_count_zone[i] = min(float(np.sum(valid2 & (overlap2 > 0))), 5.0)

    df["ob_age_norm"]     = ob_age_norm
    df["ob_size_atr"]     = ob_size_atr
    df["ob_penetration"]  = ob_penetration
    df["ob_has_fvg"]      = ob_has_fvg
    df["fvg_size_atr"]    = fvg_size_atr
    df["liq_swept_smc"]   = liq_swept_arr
    df["dist_to_liq_atr"] = dist_to_liq
    df["ob_count_zone"]   = ob_count_zone
    df["is_choch"]        = is_choch_arr

    return df


def build_features(df: pd.DataFrame, symbol: str = "XAUUSD") -> pd.DataFrame:
    """Pipeline completa di feature engineering."""
    df = add_candle_features(df)
    df = add_moving_averages(df)
    df = add_volatility(df)
    df = add_momentum(df)
    df = add_time_features(df)
    df = add_volume_features(df)
    df = add_smc_features(df)
    df = add_trend_strength(df)       # richiede atr (da add_volatility)
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
    # ── TEMPO & SESSIONE (kill zone — cruciale per XAUUSD) ───────────────────
    "hour_sin", "hour_cos", "dow_sin", "dow_cos",
    "is_london", "is_ny", "is_asia",
    # ── VOLUME (tick volume MT5 — proxy forza istituzionale) ─────────────────
    "vol_norm", "vol_spike", "vol_trend",
    # ── FORZA TREND & BANDA ──────────────────────────────────────────────────
    "adx", "bb_position", "bb_width",
    # ── SMC STRUTTURA (generali) ─────────────────────────────────────────────
    "trend_num", "bos_bull_n", "bos_bear_n", "choch_bull_n", "choch_bear_n",
    "bars_since_structure",
    # ── SMC SEGNALE (qualità setup — i discriminatori più importanti) ─────────
    "ob_age_norm",      # freschezza OB: 0=appena formato, 1=vecchio 80 bar
    "ob_size_atr",      # dimensione OB in unità ATR
    "ob_penetration",   # profondità entry: 0=bordo ideale, 1=fondo OB
    "ob_has_fvg",       # 1 se c'è FVG confluente nella zona OB (±3 ATR)
    "fvg_size_atr",     # dimensione FVG in ATR (0 se assente)
    "liq_swept_smc",    # 1 se c'è stato sweep di liquidità sul livello OB
    "dist_to_liq_atr",  # distanza alla prossima liquidità obiettivo (ATR)
    "ob_count_zone",    # OB sovrapposti nella zona (0-5)
    "is_choch",         # 1=CHoCH (inversione), 0=BOS (continuazione)
]


def build_labels(df: pd.DataFrame, lookahead: int = 10, min_move_atr: float = 1.0) -> pd.Series:
    """
    Label binaria: 1 se il trade nella direzione del trend era vincente.
    Un trade è vincente se il TP viene colpito PRIMA dello SL entro `lookahead` candele.

    Ottimizzato: matrice NumPy 2D per lookahead → elimina il doppio loop Python.
    Logica identica all'originale (controllo sequenziale, stesso tie-break).
    """
    n      = len(df)
    labels = np.zeros(n, dtype=np.int8)
    atr    = df["atr"].values
    trend  = df["trend_num"].values
    close  = df["close"].values
    high   = df["high"].values
    low    = df["low"].values

    sl_mult    = config.ATR_SL_MULTIPLIER
    rr         = config.MIN_RISK_REWARD
    valid_mask = ~np.isnan(atr) & (atr > 0)

    # ── LONG ──────────────────────────────────────────────────────────────────
    long_idx = np.where((trend == 1) & valid_mask)[0]
    long_idx = long_idx[long_idx < n - lookahead]

    if len(long_idx) > 0:
        sl = close[long_idx] - atr[long_idx] * sl_mult
        tp = close[long_idx] + atr[long_idx] * sl_mult * rr

        # Matrici (n_long, lookahead): future_low[j, k] = low[long_idx[j] + k + 1]
        future_low   = np.stack([low  [long_idx + k + 1] for k in range(lookahead)], axis=1)
        future_high  = np.stack([high [long_idx + k + 1] for k in range(lookahead)], axis=1)
        future_close = np.stack([close[long_idx + k + 1] for k in range(lookahead)], axis=1)
        future_prev  = np.stack([close[long_idx + k    ] for k in range(lookahead)], axis=1)

        sl_hits = future_low  <= sl[:, None]
        tp_hits = future_high >= tp[:, None]
        any_hit = sl_hits | tp_hits

        first_k = np.argmax(any_hit, axis=1)          # indice del primo hit
        has_hit = any_hit[np.arange(len(long_idx)), first_k]

        for j in range(len(long_idx)):
            if not has_hit[j]:
                continue
            k = first_k[j]
            i = long_idx[j]
            if sl_hits[j, k] and tp_hits[j, k]:
                labels[i] = 1 if future_close[j, k] >= future_prev[j, k] else 0
            elif tp_hits[j, k]:
                labels[i] = 1
            # sl_hit only → labels[i] rimane 0

    # ── SHORT ─────────────────────────────────────────────────────────────────
    short_idx = np.where((trend == -1) & valid_mask)[0]
    short_idx = short_idx[short_idx < n - lookahead]

    if len(short_idx) > 0:
        sl = close[short_idx] + atr[short_idx] * sl_mult
        tp = close[short_idx] - atr[short_idx] * sl_mult * rr

        future_low   = np.stack([low  [short_idx + k + 1] for k in range(lookahead)], axis=1)
        future_high  = np.stack([high [short_idx + k + 1] for k in range(lookahead)], axis=1)
        future_close = np.stack([close[short_idx + k + 1] for k in range(lookahead)], axis=1)
        future_prev  = np.stack([close[short_idx + k    ] for k in range(lookahead)], axis=1)

        sl_hits = future_high >= sl[:, None]
        tp_hits = future_low  <= tp[:, None]
        any_hit = sl_hits | tp_hits

        first_k = np.argmax(any_hit, axis=1)
        has_hit = any_hit[np.arange(len(short_idx)), first_k]

        for j in range(len(short_idx)):
            if not has_hit[j]:
                continue
            k = first_k[j]
            i = short_idx[j]
            if sl_hits[j, k] and tp_hits[j, k]:
                labels[i] = 1 if future_close[j, k] <= future_prev[j, k] else 0
            elif tp_hits[j, k]:
                labels[i] = 1

    return pd.Series(labels.astype(int), index=df.index)
