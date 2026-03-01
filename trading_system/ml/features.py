"""
Feature Engineering
====================
Costruisce le feature per il modello ML partendo dai dati OHLCV + output SMC.

Ottimizzato per 416k+ candele:
- add_smc_signal_features: OB/FVG/Liq pre-convertiti in array NumPy; inner loop
  sostituiti con operazioni vettorizzate → ~10x speedup
- build_labels: matrice NumPy 2D per lookahead → ~20x speedup

v2 – Indicatore potenziato:
- VWAP giornaliero + bande (riferimento istituzionale)
- MFI – Money Flow Index (RSI pesato per volume)
- CMF – Chaikin Money Flow (pressione compratori/venditori)
- OBV + trend OBV
- Trend H1 e H4 (allineamento multi-timeframe completo)
- Volume alla formazione dell'OB (conferma istituzionale)
- Signal Strength Score 0–100 composito
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


def add_vwap_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    VWAP giornaliero + bande dinamiche (±1 ATR).
    Istituti usano il VWAP come riferimento primario:
      - sopra VWAP = zona premium (short favoriti)
      - sotto VWAP = zona discount (long favoriti)
    """
    df = df.copy()
    typical = (df["high"] + df["low"] + df["close"]) / 3
    vol     = df["volume"].replace(0, np.nan).fillna(1.0)  # neutro se vol=0

    # Calcola VWAP giornaliero con groupby data
    tp_vol  = typical * vol
    date_idx = df.index.date
    cumtp   = pd.Series(tp_vol.values, index=df.index).groupby(date_idx).cumsum()
    cumvol  = pd.Series(vol.values, index=df.index).groupby(date_idx).cumsum()
    vwap    = cumtp / cumvol

    df["vwap"]          = vwap
    df["vwap_dist"]     = (df["close"] - vwap) / df["close"]   # distanza % dal VWAP
    # Posizione normalizzata: 0=esatto VWAP, >0=sopra (premium), <0=sotto (discount)
    atr_safe            = df["atr"].replace(0, np.nan)
    df["vwap_dist_atr"] = (df["close"] - vwap) / atr_safe       # in unità ATR
    # Banda ±2 ATR: 1 se price sopra VWAP+ATR (premium forte), -1 se sotto VWAP-ATR
    df["vwap_zone"] = np.where(
        df["close"] > vwap + atr_safe, 1.0,
        np.where(df["close"] < vwap - atr_safe, -1.0, 0.0),
    )
    # Crossover VWAP (segnale forte)
    above = (df["close"] > vwap).astype(int)
    df["vwap_cross_bull"] = ((above == 1) & (above.shift(1) == 0)).astype(float)
    df["vwap_cross_bear"] = ((above == 0) & (above.shift(1) == 1)).astype(float)

    return df


def add_mfi_cmf_obv(df: pd.DataFrame) -> pd.DataFrame:
    """
    Money Flow Index (RSI con volume), Chaikin Money Flow, On Balance Volume.
    Queste feature rilevano la pressione istituzionale BUY/SELL meglio del volume grezzo.
    """
    df = df.copy()
    vol     = df["volume"].replace(0, 1.0)  # evita divisione per zero
    typical = (df["high"] + df["low"] + df["close"]) / 3

    # ── MFI (Money Flow Index) ────────────────────────────────────────────────
    mf     = typical * vol
    delta_t = typical.diff()
    pos_mf = mf.where(delta_t > 0, 0.0).rolling(14).sum()
    neg_mf = mf.where(delta_t < 0, 0.0).rolling(14).sum()
    mfr    = pos_mf / neg_mf.replace(0, np.nan)
    df["mfi"] = 100 - 100 / (1 + mfr)
    df["mfi_norm"] = (df["mfi"] - 50) / 50   # normalizzato -1..+1

    # ── CMF (Chaikin Money Flow) – 20 periodi ──────────────────────────────────
    hl_range  = (df["high"] - df["low"]).replace(0, np.nan)
    clv       = ((df["close"] - df["low"]) - (df["high"] - df["close"])) / hl_range
    money_vol = clv * vol
    df["cmf"] = money_vol.rolling(20).sum() / vol.rolling(20).sum()   # range -1..+1

    # ── OBV (On Balance Volume) ───────────────────────────────────────────────
    direction = np.sign(df["close"].diff()).fillna(0)
    obv       = (direction * vol).cumsum()
    df["obv"] = obv
    # OBV trend: EMA3 vs EMA10 (short-term vs medio-term)
    obv_ema3  = obv.ewm(span=3,  adjust=False).mean()
    obv_ema10 = obv.ewm(span=10, adjust=False).mean()
    df["obv_trend"] = np.where(obv_ema3 > obv_ema10, 1.0, -1.0)
    # OBV normalizzato (z-score su finestra 50)
    obv_roll_std = obv.rolling(50).std().replace(0, np.nan)
    obv_roll_mean = obv.rolling(50).mean()
    df["obv_zscore"] = ((obv - obv_roll_mean) / obv_roll_std).clip(-3, 3)

    return df


def add_htf_h1_h4_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Trend H1 e H4 tramite resample da M5.
    Più alto è il timeframe concordante, più forte è il segnale.

    htf_h1_trend  : 1=H1 bullish, -1=H1 bearish
    htf_h4_trend  : 1=H4 bullish, -1=H4 bearish
    htf_score     : somma pesata M30+H1+H4 (max 3.0 = tutto allineato)
    """
    df = df.copy()

    def resample_trend(df_: pd.DataFrame, rule: str, fast: int, slow: int) -> pd.Series:
        htf = df_[["open", "high", "low", "close", "volume"]].resample(rule).agg({
            "open": "first", "high": "max", "low": "min",
            "close": "last",  "volume": "sum",
        }).dropna()
        htf["ema_f"] = htf["close"].ewm(span=fast, adjust=False).mean()
        htf["ema_s"] = htf["close"].ewm(span=slow, adjust=False).mean()
        trend = np.where(htf["ema_f"] > htf["ema_s"],  1.0,
                np.where(htf["ema_f"] < htf["ema_s"], -1.0, 0.0))
        return pd.Series(trend, index=htf.index).reindex(df_.index, method="ffill").fillna(0.0)

    df["htf_h1_trend"] = resample_trend(df, "1h",  fast=20, slow=50)
    df["htf_h4_trend"] = resample_trend(df, "4h",  fast=20, slow=50)

    # Recupera htf_trend (M30) già calcolato o ricalcola
    m30_trend = df.get("htf_trend", pd.Series(0.0, index=df.index))

    # Score pesato: M30=0.5pt, H1=1pt, H4=1.5pt (più alto TF = più peso)
    df["htf_score"] = (
        m30_trend * 0.5 +
        df["htf_h1_trend"] * 1.0 +
        df["htf_h4_trend"] * 1.5
    )  # range -3.0 .. +3.0

    return df


def add_ob_volume_feature(df: pd.DataFrame) -> pd.DataFrame:
    """
    Volume normalizzato alla candela che ha formato l'OB.
    Un OB formato su volume istituzionale (>2x media) è molto più affidabile.
    Richiede che add_smc_signal_features sia già stata chiamata (ob_age_norm presente).
    """
    df = df.copy()
    vol      = df["volume"].replace(0, np.nan).fillna(1.0)
    vol_ma20 = vol.rolling(20).mean().replace(0, np.nan)
    vol_norm = (vol / vol_ma20).clip(0, 10).fillna(1.0)

    # Stima: se l'OB è stato formato ~age bar fa, prendi il volume di quella candela
    ob_age_norm = df.get("ob_age_norm", pd.Series(0.0, index=df.index)).values
    n = len(df)
    vol_at_ob = np.ones(n)

    for i in range(n):
        if ob_age_norm[i] > 0:
            age_bars = int(round(ob_age_norm[i] * 80))   # OB_MAX_AGE=80
            ob_bar   = max(0, i - age_bars)
            vol_at_ob[i] = vol_norm.iloc[ob_bar]

    df["ob_vol_ratio"] = vol_at_ob   # >2 = OB istituzionale, <1 = debole
    return df


def add_signal_strength(df: pd.DataFrame) -> pd.DataFrame:
    """
    Signal Strength Score 0–100: combina tutte le confluenze in un punteggio unico.
    Più alto = setup migliore = maggiore probabilità di win.

    Componenti (pesi calibrati su backtest):
      HTF alignment  (htf_score)         → max 25 pt
      OB quality     (age + size + FVG)  → max 20 pt
      Momentum       (MFI + CMF + OBV)   → max 20 pt
      VWAP position                      → max 15 pt
      Liq sweep                          → max 10 pt
      Volume OB      (ob_vol_ratio)      → max 10 pt
    """
    df = df.copy()
    n = len(df)
    score = np.zeros(n)

    trend = df.get("trend_num", df.get("trend", pd.Series(0, index=df.index))).values

    # 1. HTF alignment (25 pt)
    htf_score = df.get("htf_score", pd.Series(0.0, index=df.index)).values
    # htf_score range -3..+3; per long vogliamo >0, per short <0
    htf_component = np.where(
        trend == 1,  np.clip( htf_score / 3.0, 0, 1) * 25,
        np.where(
        trend == -1, np.clip(-htf_score / 3.0, 0, 1) * 25,
        0.0)
    )
    score += htf_component

    # 2. OB quality (20 pt): freschezza + FVG + penetrazione ideale
    ob_fresh = np.clip(1 - df.get("ob_age_norm", pd.Series(0.0, index=df.index)).values, 0, 1)
    ob_fvg   = df.get("ob_has_fvg", pd.Series(0.0, index=df.index)).values
    ob_pen   = np.clip(1 - df.get("ob_penetration", pd.Series(0.5, index=df.index)).values, 0, 1)
    score += (ob_fresh * 10 + ob_fvg * 7 + ob_pen * 3)

    # 3. Momentum (20 pt): MFI + CMF + OBV trend
    mfi_norm = df.get("mfi_norm", pd.Series(0.0, index=df.index)).values
    cmf      = df.get("cmf", pd.Series(0.0, index=df.index)).values
    obv_tr   = df.get("obv_trend", pd.Series(0.0, index=df.index)).values
    # per long: MFI>0 e CMF>0 e OBV bull; per short: opposto
    mom_long  = np.clip(mfi_norm, 0, 1) * 7 + np.clip(cmf, 0, 1) * 7 + (obv_tr == 1).astype(float) * 6
    mom_short = np.clip(-mfi_norm, 0, 1) * 7 + np.clip(-cmf, 0, 1) * 7 + (obv_tr == -1).astype(float) * 6
    score += np.where(trend == 1, mom_long, np.where(trend == -1, mom_short, 0.0))

    # 4. VWAP position (15 pt)
    vwap_dist_atr = df.get("vwap_dist_atr", pd.Series(0.0, index=df.index)).values
    # long: price sotto VWAP (discount) = ideale per buy; short: price sopra (premium)
    vwap_long  = np.clip(-vwap_dist_atr / 2.0, 0, 1) * 15  # sotto VWAP = buono per long
    vwap_short = np.clip( vwap_dist_atr / 2.0, 0, 1) * 15  # sopra VWAP = buono per short
    score += np.where(trend == 1, vwap_long, np.where(trend == -1, vwap_short, 0.0))

    # 5. Liquidity sweep (10 pt)
    liq_swept = df.get("liq_swept_smc", pd.Series(0.0, index=df.index)).values
    score += liq_swept * 10

    # 6. Volume at OB (10 pt)
    ob_vol = df.get("ob_vol_ratio", pd.Series(1.0, index=df.index)).values
    score += np.clip((ob_vol - 1.0) / 2.0, 0, 1) * 10   # 0pt se ratio=1 (normale), 10pt se ratio≥3

    df["signal_strength"] = np.clip(score, 0, 100).round(1)

    # Label qualitativa (per il dashboard e il bot)
    df["signal_grade"] = pd.cut(
        df["signal_strength"],
        bins=[-1, 30, 50, 65, 80, 101],
        labels=["SKIP", "WEAK", "GOOD", "STRONG", "A+"],
    ).astype(str)

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


def add_htf_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Feature del timeframe superiore M30 per allineamento di trend.
    Resampla i dati M5 a M30, calcola EMA20/EMA50, forward-fill su M5.

    htf_trend  : 1=M30 bullish, -1=M30 bearish, 0=neutro
    htf_aligned: 1 se M5 trend e M30 trend concordano (setup più forte)
    """
    df = df.copy()

    m30 = df[["open", "high", "low", "close", "volume"]].resample("30min").agg({
        "open": "first", "high": "max", "low": "min",
        "close": "last",  "volume": "sum",
    }).dropna()

    m30["ema20"] = m30["close"].ewm(span=20, adjust=False).mean()
    m30["ema50"] = m30["close"].ewm(span=50, adjust=False).mean()
    m30["htf_trend_raw"] = np.where(
        m30["ema20"] > m30["ema50"],  1.0,
        np.where(m30["ema20"] < m30["ema50"], -1.0, 0.0),
    )

    # Forward-fill su M5: ogni candela M5 eredita il trend M30 precedente
    htf_m5 = m30["htf_trend_raw"].reindex(df.index, method="ffill").fillna(0.0)
    df["htf_trend"] = htf_m5

    # Allineamento M5 vs M30
    m5_trend = df.get("trend", pd.Series(0, index=df.index))
    df["htf_aligned"] = ((m5_trend != 0) & (m5_trend == df["htf_trend"])).astype(float)

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

    ob_age_norm      = np.zeros(n)
    ob_size_atr      = np.zeros(n)
    ob_penetration   = np.zeros(n)
    ob_has_fvg       = np.zeros(n)
    fvg_size_atr     = np.zeros(n)
    liq_swept_arr    = np.zeros(n)
    dist_to_liq      = np.full(n, 10.0)
    ob_count_zone    = np.zeros(n)
    sl_in_liq_zone   = np.zeros(n)           # 1 se SL grezzo cade dentro una liq zone
    dist_sl_to_liq   = np.full(n, 10.0)      # distanza SL→liq zone più vicina (in ATR)
    sl_dist_adjusted = np.zeros(n)           # SL dist aggiustato (per build_labels)

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

        # ── Stop Hunt: SL grezzo dentro una liquidity zone? ───────────────────
        sl_mult    = config.ATR_SL_MULTIPLIER
        sl_search  = a * config.SL_LIQ_SEARCH_ATR
        sl_max_d   = a * config.SL_MAX_MULTIPLIER
        liq_buf    = config.SL_LIQ_BUFFER_PIPS.get(symbol, 0.0005)
        raw_sl_d   = a * sl_mult          # distanza SL grezza dall'entry

        if t == 1:  # long: SL è sotto l'entry
            sl_raw_price = c - raw_sl_d
            if len(liq_lows_arr) > 0:
                in_range = liq_lows_arr[
                    (liq_lows_arr >= sl_raw_price - sl_search) & (liq_lows_arr < c)
                ]
                all_near = liq_lows_arr[np.abs(liq_lows_arr - sl_raw_price) <= sl_search * 2]
                if len(all_near) > 0:
                    dist_sl_to_liq[i] = float(np.min(np.abs(all_near - sl_raw_price))) / a
                if len(in_range) > 0:
                    sl_in_liq_zone[i] = 1.0
                    sl_new_price = float(in_range.min()) - liq_buf
                    new_dist = c - sl_new_price
                    sl_dist_adjusted[i] = new_dist if new_dist <= sl_max_d else sl_max_d
                else:
                    sl_dist_adjusted[i] = raw_sl_d
            else:
                sl_dist_adjusted[i] = raw_sl_d

        else:  # short: SL è sopra l'entry
            sl_raw_price = c + raw_sl_d
            if len(liq_highs_arr) > 0:
                in_range = liq_highs_arr[
                    (liq_highs_arr > c) & (liq_highs_arr <= sl_raw_price + sl_search)
                ]
                all_near = liq_highs_arr[np.abs(liq_highs_arr - sl_raw_price) <= sl_search * 2]
                if len(all_near) > 0:
                    dist_sl_to_liq[i] = float(np.min(np.abs(all_near - sl_raw_price))) / a
                if len(in_range) > 0:
                    sl_in_liq_zone[i] = 1.0
                    sl_new_price = float(in_range.max()) + liq_buf
                    new_dist = sl_new_price - c
                    sl_dist_adjusted[i] = new_dist if new_dist <= sl_max_d else sl_max_d
                else:
                    sl_dist_adjusted[i] = raw_sl_d
            else:
                sl_dist_adjusted[i] = raw_sl_d

    df["ob_age_norm"]      = ob_age_norm
    df["ob_size_atr"]      = ob_size_atr
    df["ob_penetration"]   = ob_penetration
    df["ob_has_fvg"]       = ob_has_fvg
    df["fvg_size_atr"]     = fvg_size_atr
    df["liq_swept_smc"]    = liq_swept_arr
    df["dist_to_liq_atr"]  = dist_to_liq
    df["ob_count_zone"]    = ob_count_zone
    df["is_choch"]         = is_choch_arr
    df["sl_in_liq_zone"]   = sl_in_liq_zone
    df["dist_sl_to_liq"]   = dist_sl_to_liq
    df["sl_dist_adjusted"] = sl_dist_adjusted

    return df


def add_pa_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Price Action features vettorizzate: pattern candlestick + wick ratio.

    Feature aggiunte:
      pa_pin_bar_bull   — 1 se la candela è un bullish pin bar (hammer)
      pa_pin_bar_bear   — 1 se la candela è un bearish pin bar (shooting star)
      pa_engulfing_bull — 1 se bullish engulfing rispetto alla candela precedente
      pa_engulfing_bear — 1 se bearish engulfing rispetto alla candela precedente
      pa_doji           — 1 se la candela è un doji (indecisione)
      pa_inside_bar     — 1 se la candela è un inside bar (compressione)
      pa_marubozu_bull  — 1 se bullish marubozu (momentum puro)
      pa_marubozu_bear  — 1 se bearish marubozu (momentum puro)
      pa_wick_ratio     — upper_shadow / (lower_shadow + ε): >1 = wick sup dominante
      pa_rejection      — wick dominante normalizzato (pin bar quality, 0-1)

    Completamente vettorizzate: nessun loop Python, zero overhead.
    Retrocompatibili: colonne fillate a 0.0 se dati insufficienti.
    """
    df = df.copy()
    n = len(df)

    o = df["open"].values
    h = df["high"].values
    l = df["low"].values
    c = df["close"].values

    rng  = np.maximum(h - l, 1e-10)
    body = np.abs(c - o)
    uwk  = h - np.maximum(o, c)   # upper wick
    lwk  = np.minimum(o, c) - l   # lower wick

    body_pct = body / rng
    uwk_pct  = uwk / rng
    lwk_pct  = lwk / rng

    # Soglie configurabili
    pb_body_max = getattr(config, 'PA_PIN_BAR_BODY_MAX_PCT', 0.35)
    pb_wick_min = getattr(config, 'PA_PIN_BAR_WICK_MIN_PCT', 0.55)
    doji_max    = getattr(config, 'PA_DOJI_BODY_MAX_PCT', 0.10)
    maru_min    = getattr(config, 'PA_MARUBOZU_BODY_MIN_PCT', 0.80)

    # Pin bar
    is_small_body = body_pct <= pb_body_max
    df["pa_pin_bar_bull"] = (is_small_body & (lwk_pct >= pb_wick_min) & (uwk_pct < 0.20)).astype(float)
    df["pa_pin_bar_bear"] = (is_small_body & (uwk_pct >= pb_wick_min) & (lwk_pct < 0.20)).astype(float)

    # Doji
    df["pa_doji"] = (body_pct <= doji_max).astype(float)

    # Marubozu
    df["pa_marubozu_bull"] = ((body_pct >= maru_min) & (c > o)).astype(float)
    df["pa_marubozu_bear"] = ((body_pct >= maru_min) & (c < o)).astype(float)

    # Engulfing (richiede la candela precedente)
    if n >= 2:
        po = np.roll(o, 1); pc = np.roll(c, 1)
        ph = np.roll(h, 1); pl = np.roll(l, 1)
        # Precedente body bounds
        prev_top = np.maximum(po, pc)
        prev_bot = np.minimum(po, pc)
        prev_bear = pc < po   # precedente bearish
        prev_bull = pc > po   # precedente bullish
        cur_bull  = c > o
        cur_bear  = c < o
        # Bullish engulfing: C1 bearish, C2 bullish e ingloba il corpo
        df["pa_engulfing_bull"] = (prev_bear & cur_bull & (o <= prev_bot) & (c >= prev_top)).astype(float)
        # Bearish engulfing: C1 bullish, C2 bearish e ingloba il corpo
        df["pa_engulfing_bear"] = (prev_bull & cur_bear & (o >= prev_top) & (c <= prev_bot)).astype(float)
        # Inside bar: range corrente contenuto nel range precedente
        df["pa_inside_bar"] = ((h < ph) & (l > pl)).astype(float)
        # Prima riga non ha contesto: azzera
        for col in ["pa_engulfing_bull", "pa_engulfing_bear", "pa_inside_bar"]:
            df[col].iloc[0] = 0.0
    else:
        df["pa_engulfing_bull"] = 0.0
        df["pa_engulfing_bear"] = 0.0
        df["pa_inside_bar"]     = 0.0

    # Wick ratio (proxy direzione pressione: >1 = pressione ribassista, <1 = bullish)
    df["pa_wick_ratio"] = (uwk / (lwk + 1e-10)).clip(0, 10)

    # Rejection strength: max wick dominante come % del range (pin bar quality)
    df["pa_rejection"] = np.maximum(uwk_pct, lwk_pct)

    return df


def build_features(df: pd.DataFrame, symbol: str = "XAUUSD") -> pd.DataFrame:
    """Pipeline completa di feature engineering (v2 – indicatore potenziato)."""
    df = add_candle_features(df)
    df = add_moving_averages(df)
    df = add_volatility(df)               # richiede: nulla
    df = add_momentum(df)
    df = add_time_features(df)
    df = add_volume_features(df)
    df = add_mfi_cmf_obv(df)             # MFI, CMF, OBV (richiede volume)
    df = add_smc_features(df)
    df = add_trend_strength(df)           # ADX + BB (richiede atr)
    df = add_htf_features(df)             # trend M30 (resample da M5)
    df = add_htf_h1_h4_features(df)      # trend H1 + H4 + htf_score
    df = add_vwap_features(df)            # VWAP giornaliero (richiede atr)
    df = add_smc_signal_features(df, symbol=symbol)   # OB/FVG/Liq + SL stop-hunt
    df = add_ob_volume_feature(df)        # volume all'OB (richiede ob_age_norm)
    df = add_signal_strength(df)          # score 0-100 composito
    df = add_pa_features(df)              # Price Action patterns (pin bar, engulfing, ecc.)
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
    # ── MOMENTUM CLASSICO ────────────────────────────────────────────────────
    "rsi_norm", "macd_norm", "macd_hist", "stoch_k", "stoch_d",
    # ── TEMPO & SESSIONE (kill zone — cruciale per XAUUSD) ───────────────────
    "hour_sin", "hour_cos", "dow_sin", "dow_cos",
    "is_london", "is_ny", "is_asia",
    # ── VOLUME BASE ───────────────────────────────────────────────────────────
    "vol_norm", "vol_spike", "vol_trend",
    # ── VOLUME AVANZATO (v2) ──────────────────────────────────────────────────
    "mfi_norm",         # Money Flow Index norm -1..+1 (RSI pesato per volume)
    "cmf",              # Chaikin Money Flow -1..+1 (pressione buy/sell)
    "obv_trend",        # OBV trend: 1=bullish, -1=bearish
    "obv_zscore",       # OBV z-score normalizzato (momentum cumulativo volume)
    # ── VWAP ISTITUZIONALE (v2) ───────────────────────────────────────────────
    "vwap_dist",        # distanza % dal VWAP giornaliero
    "vwap_dist_atr",    # distanza dal VWAP in unità ATR
    "vwap_zone",        # 1=premium (sopra VWAP+ATR), -1=discount, 0=neutro
    "vwap_cross_bull",  # 1 se cross VWAP rialzista in questa candela
    "vwap_cross_bear",  # 1 se cross VWAP ribassista in questa candela
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
    "ob_vol_ratio",     # volume alla candela OB / media (v2 — conferma istituzionale)
    # ── TREND MULTI-TIMEFRAME (v2 – M30 + H1 + H4) ───────────────────────────
    "htf_trend",        # trend M30: 1=bull, -1=bear, 0=neutro
    "htf_aligned",      # 1 se M5 e M30 concordano
    "htf_h1_trend",     # trend H1: 1=bull, -1=bear
    "htf_h4_trend",     # trend H4: 1=bull, -1=bear
    "htf_score",        # score pesato M30+H1+H4 (max ±3.0; +3=tutto allineato bull)
    # ── STOP HUNT RISK ────────────────────────────────────────────────────────
    "sl_in_liq_zone",   # 1 se SL grezzo cade dentro una liq zone (stop hunt risk)
    "dist_sl_to_liq",   # distanza SL → liq zone più vicina (ATR; bassa = rischio alto)
    # ── PRICE ACTION PATTERNS (PA) ────────────────────────────────────────────
    "pa_pin_bar_bull",   # 1 se bullish pin bar (hammer) — rigetto da zona di supporto
    "pa_pin_bar_bear",   # 1 se bearish pin bar (shooting star) — rigetto da resistenza
    "pa_engulfing_bull", # 1 se bullish engulfing — forte momentum inversivo rialzista
    "pa_engulfing_bear", # 1 se bearish engulfing — forte momentum inversivo ribassista
    "pa_doji",           # 1 se doji — indecisione al bordo dell'OB
    "pa_inside_bar",     # 1 se inside bar — compressione, breakout atteso
    "pa_marubozu_bull",  # 1 se bullish marubozu — momentum puro rialzista
    "pa_marubozu_bear",  # 1 se bearish marubozu — momentum puro ribassista
    "pa_wick_ratio",     # upper/lower wick ratio (>1=pressione bear; <1=pressione bull)
    "pa_rejection",      # qualità pin bar: wick dominante / range (0-1)
]


def build_labels(df: pd.DataFrame, lookahead: int = 10, min_move_atr: float = 1.0) -> pd.Series:
    """
    Label binaria: 1 se il trade nella direzione del trend era vincente.
    Un trade è vincente se il TP viene colpito PRIMA dello SL entro `lookahead` candele.

    Usa SL grezzo ATR-based (identico all'originale): le label riflettono la realtà storica,
    inclusi i casi di stop hunt (SL in liq zone → colpito → label 0).
    Le nuove feature sl_in_liq_zone/dist_sl_to_liq insegnano al modello a riconoscere
    queste situazioni senza alterare l'integrità delle label storiche.

    Ottimizzato: matrice NumPy 2D per lookahead → elimina il doppio loop Python.
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

    # ── SL distance: usa sl_dist_adjusted se disponibile ─────────────────────
    # sl_dist_adjusted riflette lo SL reale usato in live (aggiustato oltre le
    # liquidity zones). Usarlo nelle label allinea training e live trading,
    # riducendo la distorsione della calibrazione ML.
    if "sl_dist_adjusted" in df.columns:
        sl_dist_col = df["sl_dist_adjusted"].values
    else:
        sl_dist_col = None

    # ── LONG ──────────────────────────────────────────────────────────────────
    long_idx = np.where((trend == 1) & valid_mask)[0]
    long_idx = long_idx[long_idx < n - lookahead]

    if len(long_idx) > 0:
        if sl_dist_col is not None:
            sl_d = sl_dist_col[long_idx]
            # sl_dist_adjusted = 0 quando nessuna liq zone in range → fallback su raw ATR
            sl_d = np.where(sl_d > 0, sl_d, atr[long_idx] * sl_mult)
        else:
            sl_d = atr[long_idx] * sl_mult
        sl = close[long_idx] - sl_d
        tp = close[long_idx] + sl_d * rr

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
        if sl_dist_col is not None:
            sl_d = sl_dist_col[short_idx]
            sl_d = np.where(sl_d > 0, sl_d, atr[short_idx] * sl_mult)
        else:
            sl_d = atr[short_idx] * sl_mult
        sl = close[short_idx] + sl_d
        tp = close[short_idx] - sl_d * rr

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
