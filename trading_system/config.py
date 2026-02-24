"""
Trading System Configuration
=============================
Parametri configurabili per il sistema di trading automatico.
"""

# ─── DATA SOURCES ────────────────────────────────────────────────────────────

# Default timeframe per i candlestick
DEFAULT_INTERVAL = "1h"          # 1m, 5m, 15m, 30m, 1h, 4h, 1d
DEFAULT_PERIOD = "60d"           # quanti dati storici scaricare

# ─── INDICATORI TECNICI ───────────────────────────────────────────────────────

RSI_PERIOD = 14
RSI_OVERSOLD = 30               # segnale BUY sotto questa soglia
RSI_OVERBOUGHT = 70             # segnale SELL sopra questa soglia

MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9

BB_PERIOD = 20
BB_STD = 2.0

EMA_SHORT = 9
EMA_LONG = 21
EMA_TREND = 50                  # EMA di tendenza principale

ADX_PERIOD = 14
ADX_THRESHOLD = 25              # trend forte sopra questa soglia

STOCH_K = 14
STOCH_D = 3
STOCH_SMOOTH = 3
STOCH_OVERSOLD = 20
STOCH_OVERBOUGHT = 80

VOLUME_MA_PERIOD = 20           # media mobile volume
VOLUME_MULTIPLIER = 1.5         # volume deve essere X volte la media

# ─── SIGNAL GENERATOR ─────────────────────────────────────────────────────────

# Pesi degli indicatori per il calcolo del punteggio di confidenza
INDICATOR_WEIGHTS = {
    "rsi": 0.20,
    "macd": 0.20,
    "ema_cross": 0.20,
    "bollinger": 0.15,
    "stochastic": 0.10,
    "adx": 0.10,
    "volume": 0.05,
}

# Soglia minima di confidenza per generare un segnale (0.0 - 1.0)
# 0.75 = almeno il 75% degli indicatori devono concordare
MIN_CONFIDENCE_THRESHOLD = 0.75

# ─── RISK MANAGEMENT ──────────────────────────────────────────────────────────

# Stop-loss e take-profit di default (percentuale dal prezzo di entrata)
DEFAULT_STOP_LOSS_PCT = 0.02     # 2%
DEFAULT_TAKE_PROFIT_PCT = 0.04   # 4%  (risk/reward 1:2)

# ATR-based stop loss (usa volatilità reale del mercato)
USE_ATR_STOP = True
ATR_PERIOD = 14
ATR_MULTIPLIER = 2.0             # stop = ATR * moltiplicatore

# Dimensione posizione (percentuale del capitale)
POSITION_SIZE_PCT = 0.10         # rischia max 10% del capitale per trade
MAX_RISK_PER_TRADE = 0.02        # rischia max 2% del capitale per stop

# Numero massimo di posizioni aperte contemporaneamente
MAX_OPEN_POSITIONS = 3

# ─── BACKTESTING ──────────────────────────────────────────────────────────────

BACKTEST_INITIAL_CAPITAL = 10_000.0   # capitale iniziale simulato (€/$)
BACKTEST_COMMISSION = 0.001           # 0.1% commissione per trade (Binance/IBKR)
BACKTEST_SLIPPAGE = 0.0005            # 0.05% slippage simulato

# ─── PAPER TRADING ────────────────────────────────────────────────────────────

PAPER_INITIAL_CAPITAL = 10_000.0

# ─── LIVE TRADING (Binance) ───────────────────────────────────────────────────
# Mettere le chiavi API qui o in variabili di ambiente:
# BINANCE_API_KEY e BINANCE_SECRET_KEY

BINANCE_API_KEY = ""             # oppure os.environ.get("BINANCE_API_KEY")
BINANCE_SECRET_KEY = ""          # oppure os.environ.get("BINANCE_SECRET_KEY")
BINANCE_TESTNET = True           # True = testnet (sicuro), False = mainnet (reale)

# ─── NOTIFICHE ────────────────────────────────────────────────────────────────

TELEGRAM_BOT_TOKEN = ""
TELEGRAM_CHAT_ID = ""

# ─── LOGGING ──────────────────────────────────────────────────────────────────

LOG_LEVEL = "INFO"               # DEBUG, INFO, WARNING, ERROR
LOG_FILE = "trading.log"
