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
import json
import logging
from datetime import datetime
from pathlib import Path

# Aggiungi root al path
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

STATE_FILE   = os.path.join(ROOT, "trading_system", "state.json")
CONTROL_FILE = os.path.join(ROOT, "trading_system", "control.json")

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

    # Carica modelli ML (solo se USE_ML_FILTER abilitato)
    ml_models = {}
    if config.USE_ML_FILTER:
        for symbol in config.SYMBOLS:
            ml = SMCMLModel(symbol)
            try:
                ml.load()
                ml_models[symbol] = ml
            except FileNotFoundError as e:
                logger.error(str(e))
                sys.exit(1)
        logger.info(f"Modelli ML caricati: {list(ml_models.keys())}")
    else:
        logger.info("Filtro ML disabilitato (USE_ML_FILTER=False) — solo SMC")

    # SMC Detectors
    smc_detectors = {s: SMCDetector(s) for s in config.SYMBOLS}

    logger.info(f"Simboli: {config.SYMBOLS}")
    logger.info("Sistema pronto. In attesa kill zone...\n")

    return connector, executor, risk_manager, session_f, news_f, ml_models, smc_detectors


# ─── STATE FILE ───────────────────────────────────────────────────────────────

# Stato per la dashboard (aggiornato ad ogni ciclo)
_symbol_signals: dict = {}
_block_reasons:  list = []   # [{"level": "info"|"warn"|"ok", "msg": "..."}]


def _reason(level: str, msg: str):
    """Aggiunge un motivo alla lista corrente di block reasons."""
    _block_reasons.append({"level": level, "msg": msg})


def write_state(risk_manager, session_f, bot_status: str = "running"):
    """Scrive lo stato corrente su state.json per la dashboard."""
    try:
        status = risk_manager.status()

        def trade_to_dict(t):
            return {
                "symbol":      t.symbol,
                "direction":   t.direction,
                "lot_size":    t.lot_size,
                "entry_price": t.entry,
                "sl":          t.sl,
                "tp":          t.tp,
                "pnl":         t.pnl,
                "open_time":   t.open_time.isoformat() if t.open_time else None,
                "close_time":  t.close_time.isoformat() if t.close_time else None,
                "result":      t.result,
            }

        state = {
            "bot_status":         bot_status,
            "timestamp":          datetime.now().isoformat(),
            "session":            session_f.active_session(),
            "minutes_to_next":    session_f.minutes_to_next_session(),
            "balance":            status["balance"],
            "daily_dd_pct":       status["daily_drawdown_pct"],
            "total_dd_pct":       status["total_drawdown_pct"],
            "trades_today":       status["trades_today"],
            "win_rate":           status["win_rate"],
            "consecutive_losses": status["consecutive_losses"],
            "open_positions":     status["open_positions"],
            "total_wins":         status["total_wins"],
            "total_losses":       status["total_losses"],
            "symbols":            _symbol_signals,
            "block_reasons":      list(_block_reasons),
            "open_trades":        [trade_to_dict(t) for t in risk_manager.open_trades],
            "closed_trades":      [trade_to_dict(t) for t in risk_manager.closed_trades],
        }
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
    except Exception as e:
        logger.debug(f"[Dashboard] Errore scrittura state.json: {e}")


def check_control() -> str:
    """
    Legge control.json scritto dalla dashboard.
    Ritorna 'stop', 'start' o '' se nessun comando.
    """
    if not os.path.exists(CONTROL_FILE):
        return ""
    try:
        with open(CONTROL_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        os.remove(CONTROL_FILE)
        return data.get("action", "")
    except Exception:
        return ""


# ─── CICLO PRINCIPALE ─────────────────────────────────────────────────────────

def run_cycle(connector, executor, risk_manager, session_f, news_f, ml_models, smc_detectors):
    """
    Eseguito ogni 60 secondi (inizio candela M5 = ogni 300s, ma controlliamo ogni 60s).
    """
    global _symbol_signals, _block_reasons
    _block_reasons = []   # reset ad ogni ciclo
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
        _reason("warn", f"EOD – nessun nuovo trade oltre le {config.PROP_CLOSE_EOD_HOUR}:00")
        return

    # ── 2. SESSIONE ───────────────────────────────────────────────────────────
    session = session_f.active_session()
    if session in ("CLOSED", "EOD"):
        mins = session_f.minutes_to_next_session()
        if now.minute % 30 == 0:  # log ogni 30 min
            logger.info(f"[BOT] Sessione {session} | Prossima kill zone tra {mins} min")
        h, m = divmod(mins, 60)
        timer_str = f"{h}h {m}m" if h else f"{m}m"
        _reason("info", f"Sessione chiusa – prossima kill zone tra {timer_str}")
        return

    # ── 3. NEWS FILTER ────────────────────────────────────────────────────────
    if not news_f.is_safe():
        event = news_f.next_blocked_event()
        logger.info(f"[BOT] Blocco news attivo | {event}")
        _reason("warn", f"News ad alto impatto: {event}")
        return

    # ── 4. RISK CHECK ─────────────────────────────────────────────────────────
    can, reason = risk_manager.can_trade()
    if not can:
        logger.warning(f"[BOT] Trading bloccato: {reason}")
        _reason("warn", reason)
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
            _reason("warn", f"{symbol}: errore analisi – {e}")

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

    # Aggiorna dashboard
    write_state(risk_manager, session_f)


def analyze_symbol(symbol, connector, executor, risk_manager, ml_model, smc_detector, session):
    """Analizza un singolo simbolo e apre un trade se il setup è valido."""
    global _symbol_signals

    # Recupera ultime 200 candele M5
    df = connector.get_ohlcv(symbol, timeframe=config.TIMEFRAME, n_candles=200)
    if df is None or len(df) < 100:
        _reason("info", f"{symbol}: dati insufficienti")
        return

    # SMC analysis
    signal = smc_detector.analyze(df)
    if signal is None:
        _symbol_signals[symbol] = {"last_signal": None, "confidence": 0.0, "reason": None}
        _reason("info", f"{symbol}: nessun setup SMC valido (struttura non confermata)")
        return

    logger.info(
        f"[SMC] {symbol} segnale {signal.direction.upper()}: {signal.reason}"
    )

    # Feature engineering per ML
    df_struct = detect_structure(df)
    df_feat   = build_features(df_struct, symbol=symbol)

    if len(df_feat) < 10:
        _reason("info", f"{symbol}: feature insufficienti per ML")
        return

    # ML confidence check
    confidence = ml_model.predict_proba(df_feat)
    logger.info(f"[ML]  {symbol} confidence: {confidence:.3f} (soglia: {config.ML_CONFIDENCE_THRESHOLD})")

    # Aggiorna segnale per la dashboard
    _symbol_signals[symbol] = {
        "last_signal": signal.direction.upper(),
        "confidence":  round(float(confidence), 3),
        "reason":      signal.reason,
    }

    if confidence < config.ML_CONFIDENCE_THRESHOLD:
        logger.info(f"[ML]  {symbol} segnale scartato (confidence insufficiente)")
        _reason(
            "info",
            f"{symbol}: segnale {signal.direction.upper()} scartato – "
            f"ML {confidence:.2f} < soglia {config.ML_CONFIDENCE_THRESHOLD}",
        )
        return

    # Verifica che non ci siano già posizioni aperte per questo simbolo
    open_pos = connector.get_open_positions(symbol=symbol)
    if open_pos:
        logger.info(f"[BOT] {symbol} posizione già aperta, skip")
        _reason("info", f"{symbol}: posizione già aperta, attendo chiusura")
        return

    # Calcola lot size
    lot = risk_manager.calculate_lot_size(
        symbol=symbol,
        entry_price=signal.entry_price,
        sl_price=signal.sl_price,
    )

    if lot <= 0:
        logger.warning(f"[Risk] Lot size non valido per {symbol}")
        _reason("warn", f"{symbol}: lot size non calcolabile (SL troppo vicino all'entry?)")
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
        _reason("ok", f"{symbol}: trade {signal.direction.upper()} aperto – lot={lot} | {signal.reason} | ML={confidence:.2f}")
    else:
        _reason("warn", f"{symbol}: ordine rifiutato da MT5")


# ─── ENTRY POINT ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    components = initialize()
    connector  = components[0]

    try:
        while True:
            # Controlla comandi dalla dashboard
            cmd = check_control()
            if cmd == "stop":
                logger.info("[BOT] Comando STOP ricevuto dalla dashboard.")
                write_state(components[2], components[3], bot_status="stopped")
                break

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
