"""
Main Bot Loop – SMC + ML Trading System
=========================================
Uso:
    python trading_system/bot.py

Prerequisiti:
    1. Modelli addestrati: python trading_system/ml/train.py
    2. MT5 installato su Windows e configurato in config.py
    3. pip install -r requirements.txt
"""

import os
import sys
import time
import logging
from datetime import datetime

# Aggiungi root al path
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from trading_system import config
from trading_system.mt5.connector import MT5Connector
from trading_system.mt5.executor import OrderExecutor
from trading_system.smc.detector import SMCDetector
from trading_system.ml.model import SMCMLModel
from trading_system.ml.features import build_features
from trading_system.smc.structure import detect_structure
from trading_system.filters.session import SessionFilter
from trading_system.filters.news import NewsFilter
from trading_system.risk.manager import RiskManager

# ─── LOGGING ──────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL),
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(config.LOG_FILE),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger(__name__)


# ─── INIZIALIZZAZIONE ─────────────────────────────────────────────────────────

def initialize():
    """Carica tutti i componenti del sistema."""
    logger.info("=" * 60)
    logger.info("  SMC + ML Trading Bot – Avvio")
    logger.info("=" * 60)

    # Connessione MT5
    connector = MT5Connector()
    if not connector.connect():
        logger.error("Impossibile connettersi a MT5. Controlla config.py")
        sys.exit(1)

    balance = connector.get_account_balance()
    logger.info(f"Saldo iniziale: {balance:.2f}")

    # Componenti
    executor     = OrderExecutor(connector)
    risk_manager = RiskManager(balance)
    session_f    = SessionFilter()
    news_f       = NewsFilter()

    # Carica modelli ML
    ml_models = {}
    for symbol in config.SYMBOLS:
        ml = SMCMLModel(symbol)
        try:
            ml.load()
            ml_models[symbol] = ml
        except FileNotFoundError as e:
            logger.error(str(e))
            sys.exit(1)

    # SMC Detectors
    smc_detectors = {s: SMCDetector(s) for s in config.SYMBOLS}

    logger.info(f"Simboli: {config.SYMBOLS}")
    logger.info(f"Modelli ML caricati: {list(ml_models.keys())}")
    logger.info("Sistema pronto. In attesa kill zone...\n")

    return connector, executor, risk_manager, session_f, news_f, ml_models, smc_detectors


# ─── CICLO PRINCIPALE ─────────────────────────────────────────────────────────

def run_cycle(connector, executor, risk_manager, session_f, news_f, ml_models, smc_detectors):
    """
    Eseguito ogni 60 secondi (inizio candela M5 = ogni 300s, ma controlliamo ogni 60s).
    """
    now = datetime.now()

    # Aggiorna saldo
    balance = connector.get_account_balance()
    risk_manager.update_balance(balance)

    # ── 1. CHIUSURA EOD ───────────────────────────────────────────────────────
    if now.hour >= config.PROP_CLOSE_EOD_HOUR:
        open_pos = connector.get_open_positions()
        if open_pos:
            logger.info("[BOT] EOD: chiusura tutte le posizioni aperte")
            executor.close_all()
        return

    # ── 2. SESSIONE ───────────────────────────────────────────────────────────
    session = session_f.active_session()
    if session in ("CLOSED", "EOD"):
        mins = session_f.minutes_to_next_session()
        if now.minute % 30 == 0:  # log ogni 30 min
            logger.info(f"[BOT] Sessione {session} | Prossima kill zone tra {mins} min")
        return

    # ── 3. NEWS FILTER ────────────────────────────────────────────────────────
    if not news_f.is_safe():
        logger.info(f"[BOT] Blocco news attivo | {news_f.next_blocked_event()}")
        return

    # ── 4. RISK CHECK ─────────────────────────────────────────────────────────
    can, reason = risk_manager.can_trade()
    if not can:
        logger.warning(f"[BOT] Trading bloccato: {reason}")
        return

    # ── 5. ANALISI SIMBOLI ────────────────────────────────────────────────────
    for symbol in config.SYMBOLS:
        try:
            analyze_symbol(
                symbol, connector, executor,
                risk_manager, ml_models[symbol],
                smc_detectors[symbol], session,
            )
        except Exception as e:
            logger.error(f"[BOT] Errore analisi {symbol}: {e}", exc_info=True)

    # Status log ogni 5 minuti
    if now.minute % 5 == 0:
        status = risk_manager.status()
        logger.info(
            f"[STATUS] Balance={status['balance']:.2f} | "
            f"DD_daily={status['daily_drawdown_pct']}% | "
            f"Trades_oggi={status['trades_today']} | "
            f"Win_rate={status['win_rate']}% | "
            f"Sessione={session}"
        )


def analyze_symbol(symbol, connector, executor, risk_manager, ml_model, smc_detector, session):
    """Analizza un singolo simbolo e apre un trade se il setup è valido."""

    # Recupera ultime 200 candele M5
    df = connector.get_ohlcv(symbol, timeframe=config.TIMEFRAME, n_candles=200)
    if df is None or len(df) < 100:
        return

    # SMC analysis
    signal = smc_detector.analyze(df)
    if signal is None:
        return

    logger.info(
        f"[SMC] {symbol} segnale {signal.direction.upper()}: {signal.reason}"
    )

    # Feature engineering per ML
    df_struct = detect_structure(df)
    df_feat   = build_features(df_struct)

    if len(df_feat) < 10:
        return

    # ML confidence check
    confidence = ml_model.predict_proba(df_feat)
    logger.info(f"[ML]  {symbol} confidence: {confidence:.3f} (soglia: {config.ML_CONFIDENCE_THRESHOLD})")

    if confidence < config.ML_CONFIDENCE_THRESHOLD:
        logger.info(f"[ML]  {symbol} segnale scartato (confidence insufficiente)")
        return

    # Verifica che non ci siano già posizioni aperte per questo simbolo
    open_pos = connector.get_open_positions(symbol=symbol)
    if open_pos:
        logger.info(f"[BOT] {symbol} posizione già aperta, skip")
        return

    # Calcola lot size
    lot = risk_manager.calculate_lot_size(
        symbol=symbol,
        entry_price=signal.entry_price,
        sl_price=signal.sl_price,
    )

    if lot <= 0:
        logger.warning(f"[Risk] Lot size non valido per {symbol}")
        return

    logger.info(
        f"[BOT] APERTURA TRADE: {symbol} {signal.direction.upper()} "
        f"lot={lot} | {signal.reason} | ML={confidence:.3f}"
    )

    # Esegui ordine
    trade = executor.open_trade(
        symbol=symbol,
        direction=signal.direction,
        lot_size=lot,
        sl_price=signal.sl_price,
        tp_price=signal.tp_price,
        comment=f"SMC+ML {session}",
    )

    if trade:
        risk_manager.register_trade_open(trade)


# ─── ENTRY POINT ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    components = initialize()
    connector  = components[0]

    try:
        while True:
            run_cycle(*components)
            time.sleep(60)   # check ogni 60 secondi

    except KeyboardInterrupt:
        logger.info("\n[BOT] Interruzione manuale. Chiusura...")
        executor = components[1]
        executor.close_all()
        connector.disconnect()
        logger.info("[BOT] Bot fermato.")

    except Exception as e:
        logger.critical(f"[BOT] Errore critico: {e}", exc_info=True)
        executor = components[1]
        executor.close_all()
        connector.disconnect()
        sys.exit(1)
