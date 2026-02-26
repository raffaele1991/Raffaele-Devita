"""
Trading System Configuration
=============================
Sistema ibrido SMC + ML per XAUUSD e EURUSD su M5.
Ottimizzato per prop firm (FTMO, MyFundedFX, The5ers).
"""

# ─── SIMBOLI ──────────────────────────────────────────────────────────────────

SYMBOLS = ["XAUUSD", "EURUSD"]
TIMEFRAME = "M5"

# ─── CARTELLE ─────────────────────────────────────────────────────────────────

DATA_DIR   = "trading_system/data"     # metti qui i CSV esportati da MT5
MODELS_DIR = "trading_system/models"  # qui vengono salvati i modelli addestrati

# ─── SESSIONI (Kill Zone) ──────────────────────────────────────────────────────
# Orari in CET (Central European Time, UTC+1 / UTC+2 in estate)
# Il bot opera SOLO in queste finestre

SESSION_LONDON_START = "08:00"
SESSION_LONDON_END   = "11:00"

SESSION_NY_START     = "14:00"
SESSION_NY_END       = "17:00"

# ─── FILTRO NEWS ──────────────────────────────────────────────────────────────

NEWS_BUFFER_MINUTES = 30   # stop trading X minuti prima/dopo news ad alto impatto

# ─── SMC – SMART MONEY CONCEPTS ───────────────────────────────────────────────

# Structure
SMC_SWING_LOOKBACK    = 10   # candele per identificare swing high/low
SMC_BOS_CONFIRMATION  = 2    # candele di chiusura oltre il livello per confermare BOS

# Order Block
OB_LOOKBACK           = 20   # quante candele cercare per l'OB
OB_MIN_CANDLE_BODY_PCT = 0.4  # corpo della candela OB deve essere almeno 40% del range

# Fair Value Gap
FVG_MIN_SIZE_PIPS     = {"XAUUSD": 1.0, "EURUSD": 0.0005}  # dimensione minima FVG

# Liquidity
LIQ_LOOKBACK          = 50   # candele per trovare livelli di liquidità (equal highs/lows)
LIQ_TOLERANCE_PIPS    = {"XAUUSD": 0.5, "EURUSD": 0.0002}  # tolleranza per "equal"

# ─── ML – MACHINE LEARNING ────────────────────────────────────────────────────

USE_ML_FILTER           = True   # True = filtra segnali con ML | False = solo SMC
ML_CONFIDENCE_THRESHOLD = 0.42   # soglia confidence calibrata

# ── FILTRI CONFLUENZA SMC ──────────────────────────────────────────────────────
# Backtest out-of-sample (2026-01-01 → 2026-02-25, XAUUSD) ha dimostrato:
#   FVG richiesto         → +6.7pp WR,  PF: 0.89→1.17
#   FVG + Liq Sweep       → +7.6pp WR,  PF: 0.89→1.20, Net=+4.00%
#   FVG + HTF alignment   → +8.5pp WR,  PF: 0.89→1.21, Sharpe=1.48, MaxDD=4.61%
#
# REQUIRE_FVG = True  → accetta solo OB con Fair Value Gap confluente nella zona
# REQUIRE_LIQ_SWEEP   → accetta solo OB dopo sweep di liquidità
SMC_REQUIRE_FVG         = True   # FVG confluence obbligatorio (default se simbolo non in SYMBOL_FILTER_CONFIGS)
SMC_REQUIRE_LIQ_SWEEP   = False  # Liq sweep (default)
SMC_REQUIRE_HTF_ALIGN   = True   # allineamento trend M30 (EMA120/300 su M5, equivale EMA20/50 su M30)

# ── CONFIG PER-SIMBOLO ─────────────────────────────────────────────────────────
# Sovrascrivono SMC_REQUIRE_* sopra per i simboli specificati.
# Motivazione:
#   XAUUSD – FVG abbondante (54% segnali), efficace come filtro
#   EURUSD – FVG rarissimo (2%), inutilizzabile; Liq Sweep abbondante (96%)
#
# Backtest out-of-sample 2026-01-01→2026-02-25:
#   XAUUSD: ML + FVG + HTF       → 55 tr  WR=41.8%  PF=1.21  Sharpe=1.48
#   EURUSD: ML + LiqSweep + HTF  → 35 tr  WR=51.4%  PF=1.49  Sharpe=2.94
#   TOTALE COMBINATO              → 90 tr in 55 giorni (~1.6 trade/giorno)
SYMBOL_FILTER_CONFIGS: dict = {
    "XAUUSD": {"require_fvg": True,  "require_liq_sweep": False, "htf_align": True},
    "EURUSD": {"require_fvg": False, "require_liq_sweep": True,  "htf_align": True},
}
ML_LOOKBACK_CANDLES     = 50     # candele di contesto passato come feature
ML_TRAIN_TEST_SPLIT     = 0.85   # 85% train, 15% test
ML_RANDOM_SEED          = 42

# Data cutoff: il modello viene trainato SOLO sui dati precedenti a questa data.
# Il backtest out-of-sample va eseguito da questa data in poi.
TRAIN_CUTOFF_DATE       = "2026-01-01"  # train su tutto il 2025, backtest out-of-sample su gen-feb 2026

# Lookahead etichette (candele M5 future per valutare TP/SL)
# 50 candele M5 = ~4 ore — dà più tempo al trade di raggiungere il TP prima di expirare
# Aumentato da 30 per migliorare la qualità delle label (meno falsi negativi per trade
# lenti ma vincenti) e alzare il win rate del modello.
ML_LOOKAHEAD             = 50

# Parametri modello (LightGBM)
ML_N_ESTIMATORS          = 3000   # max alberi — early stopping troverà il numero ottimale
ML_NUM_LEAVES            = 127    # profondità ~7 — più espressivo senza overfitting
ML_LEARNING_RATE         = 0.03   # più lento = più robusto (early stopping compensa)
ML_SUBSAMPLE             = 0.8    # bagging per ridurre overfitting
ML_COLSAMPLE_BYTREE      = 0.75   # fraction di feature per albero (più diversità)
ML_MIN_CHILD_SAMPLES     = 30     # foglie più robuste (meno overfitting su dati finanziari)
ML_REG_ALPHA             = 0.1    # L1 regularization
ML_REG_LAMBDA            = 1.0    # L2 regularization (aumentata per evitare overfitting)
ML_EARLY_STOPPING_ROUNDS = 150    # più pazienza — con LR bassa servono più round

# GPU per training LightGBM
# 'cpu'  = solo CPU (default sicuro)
# 'gpu'  = OpenCL — AMD RX 9070 / qualsiasi GPU con driver OpenCL (consigliato)
# 'cuda' = CUDA — solo GPU NVIDIA
# NOTA: richiede LightGBM con GPU support (su Windows: pip install lightgbm lo include già)
ML_DEVICE                = 'cpu'

# ─── RISK MANAGEMENT – PROP FIRM COMPLIANT ────────────────────────────────────

# Regole prop firm standard (compatibile FTMO / MyFundedFX / The5ers)
PROP_MAX_DAILY_LOSS_PCT  = 0.03   # bot si ferma al 3% (prop limit è 4-5%)
PROP_MAX_TOTAL_LOSS_PCT  = 0.07   # bot si ferma al 7% (prop limit è 8-10%)
PROP_MAX_TRADES_PER_DAY  = 3      # massimo 3 trade al giorno
PROP_CLOSE_EOD_HOUR      = 21     # chiude tutto alle 21:00 CET (no overnight)

# Sizing
RISK_PER_TRADE_PCT       = 0.005  # rischia 0.5% del capitale per trade
MIN_RISK_REWARD          = 2.0    # minimo R:R 1:2 per entrare

# Stop Loss via ATR
ATR_PERIOD               = 14
ATR_SL_MULTIPLIER        = 1.5    # SL = ATR * 1.5

# Stop Hunt / Liquidity Zone SL Protection
# Se lo SL grezzo (ATR-based) cade dentro o vicino a una liquidity zone (equal highs/lows),
# lo SL viene spostato OLTRE la zona per evitare lo stop hunt.
SL_LIQ_SEARCH_ATR    = 0.5   # cerca liq zones fino a 0.5 ATR oltre lo SL grezzo
SL_LIQ_BUFFER_PIPS   = {"XAUUSD": 2.0, "EURUSD": 0.0005}  # buffer aggiunto oltre la zona
SL_MAX_MULTIPLIER    = 3.0   # se SL aggiustato > ATR * 3.0, il trade viene skippato (R:R troppo stretto)

# Consecutive losses protection
MAX_CONSECUTIVE_LOSSES   = 2      # dopo 2 stop consecutivi, stop per oggi

# ─── MT5 CONNECTION ───────────────────────────────────────────────────────────

MT5_ACCOUNT  = 0        # inserisci il numero conto FTMO demo
MT5_PASSWORD = ""       # password conto
MT5_SERVER   = ""       # server FTMO (es. "FTMO-Demo")

# ─── NOTIFICHE TELEGRAM ───────────────────────────────────────────────────────

TELEGRAM_BOT_TOKEN = ""
TELEGRAM_CHAT_ID   = ""

# ─── LOGGING ──────────────────────────────────────────────────────────────────

LOG_LEVEL = "INFO"
LOG_FILE  = "trading_system/trading.log"
