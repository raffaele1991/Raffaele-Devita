"""
Order Executor
===============
Apre e chiude ordini su MT5 con gestione degli errori.
"""

import time
import logging
from datetime import datetime
from typing import Optional

try:
    import MetaTrader5 as mt5
    MT5_AVAILABLE = True
except ImportError:
    MT5_AVAILABLE = False
    mt5 = None

from trading_system import config
from trading_system.risk.manager import TradeRecord

logger = logging.getLogger(__name__)


class OrderExecutor:
    """
    Esegue ordini di mercato su MT5 con SL e TP già calcolati dal RiskManager.
    """

    def __init__(self, connector):
        self.connector = connector

    def open_trade(
        self,
        symbol: str,
        direction: str,       # "long" o "short"
        lot_size: float,
        sl_price: float,
        tp_price: float,
        comment: str = "SMC+ML",
    ) -> Optional[TradeRecord]:
        """
        Apre un ordine a mercato.
        Ritorna TradeRecord se va a buon fine, None altrimenti.
        """
        if not MT5_AVAILABLE or not self.connector.connected:
            logger.error("[Exec] MT5 non disponibile")
            return None

        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            logger.error(f"[Exec] Impossibile leggere tick per {symbol}")
            return None

        order_type = mt5.ORDER_TYPE_BUY if direction == "long" else mt5.ORDER_TYPE_SELL
        price      = tick.ask if direction == "long" else tick.bid

        request = {
            "action":    mt5.TRADE_ACTION_DEAL,
            "symbol":    symbol,
            "volume":    lot_size,
            "type":      order_type,
            "price":     price,
            "sl":        round(sl_price, 5),
            "tp":        round(tp_price, 5),
            "deviation": 10,           # max slippage in punti
            "magic":     20250101,     # ID univoco del nostro bot
            "comment":   comment,
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }

        result = mt5.order_send(request)

        if result is None:
            logger.error(f"[Exec] order_send ritornato None per {symbol}")
            return None

        if result.retcode != mt5.TRADE_RETCODE_DONE:
            logger.error(
                f"[Exec] Ordine rifiutato {symbol}: "
                f"retcode={result.retcode} comment={result.comment}"
            )
            return None

        trade = TradeRecord(
            symbol=symbol,
            direction=direction,
            entry=result.price if result.price else price,
            sl=sl_price,
            tp=tp_price,
            lot_size=lot_size,
            open_time=datetime.now(),
        )

        logger.info(
            f"[Exec] ORDINE APERTO: {symbol} {direction.upper()} "
            f"lot={lot_size} entry={result.price if result.price else price:.5f} "
            f"sl={sl_price:.5f} tp={tp_price:.5f}"
        )
        return trade

    def close_trade(self, trade: TradeRecord) -> Optional[float]:
        """
        Chiude una posizione aperta.
        Ritorna il PnL (approssimativo) se va a buon fine.
        """
        if not MT5_AVAILABLE or not self.connector.connected:
            return None

        positions = mt5.positions_get(symbol=trade.symbol)
        if not positions:
            logger.warning(f"[Exec] Nessuna posizione aperta per {trade.symbol}")
            return None

        # Trova la posizione del nostro bot (magic number)
        position = next(
            (p for p in positions if p.magic == 20250101), None
        )
        if position is None:
            return None

        direction_close = (
            mt5.ORDER_TYPE_SELL if trade.direction == "long"
            else mt5.ORDER_TYPE_BUY
        )
        tick = mt5.symbol_info_tick(trade.symbol)
        price = tick.bid if trade.direction == "long" else tick.ask

        request = {
            "action":    mt5.TRADE_ACTION_DEAL,
            "symbol":    trade.symbol,
            "volume":    trade.lot_size,
            "type":      direction_close,
            "position":  position.ticket,
            "price":     price,
            "deviation": 10,
            "magic":     20250101,
            "comment":   "SMC+ML close",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }

        result = mt5.order_send(request)
        if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
            logger.error(f"[Exec] Chiusura fallita {trade.symbol}: {result}")
            return None

        pnl = position.profit
        logger.info(f"[Exec] POSIZIONE CHIUSA: {trade.symbol} PnL={pnl:.2f}")
        return pnl

    def close_all(self):
        """Chiude tutte le posizioni aperte del bot (EOD)."""
        if not MT5_AVAILABLE or not self.connector.connected:
            return

        positions = mt5.positions_get()
        if not positions:
            return

        for pos in positions:
            if pos.magic != 20250101:
                continue   # non è un nostro trade

            direction_close = (
                mt5.ORDER_TYPE_SELL if pos.type == mt5.ORDER_TYPE_BUY
                else mt5.ORDER_TYPE_BUY
            )
            tick  = mt5.symbol_info_tick(pos.symbol)
            price = tick.bid if pos.type == mt5.ORDER_TYPE_BUY else tick.ask

            request = {
                "action":    mt5.TRADE_ACTION_DEAL,
                "symbol":    pos.symbol,
                "volume":    pos.volume,
                "type":      direction_close,
                "position":  pos.ticket,
                "price":     price,
                "deviation": 20,
                "magic":     20250101,
                "comment":   "EOD close",
                "type_filling": mt5.ORDER_FILLING_IOC,
            }
            result = mt5.order_send(request)
            if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                logger.info(f"[Exec] EOD chiuso: {pos.symbol} ticket={pos.ticket}")
            else:
                logger.error(f"[Exec] EOD chiusura fallita: {pos.symbol}")
