"""
MT5 Connector
==============
Connessione e recupero dati da MetaTrader 5.
Richiede: pip install MetaTrader5
"""

import time
import logging
import pandas as pd
from datetime import datetime
from typing import Optional

try:
    import MetaTrader5 as mt5
    MT5_AVAILABLE = True
except ImportError:
    MT5_AVAILABLE = False
    mt5 = None

from trading_system import config

logger = logging.getLogger(__name__)

# Mappa timeframe stringa → costante MT5
TIMEFRAME_MAP = {
    "M1":  mt5.TIMEFRAME_M1  if MT5_AVAILABLE else 1,
    "M5":  mt5.TIMEFRAME_M5  if MT5_AVAILABLE else 5,
    "M15": mt5.TIMEFRAME_M15 if MT5_AVAILABLE else 15,
    "M30": mt5.TIMEFRAME_M30 if MT5_AVAILABLE else 30,
    "H1":  mt5.TIMEFRAME_H1  if MT5_AVAILABLE else 60,
    "H4":  mt5.TIMEFRAME_H4  if MT5_AVAILABLE else 240,
    "D1":  mt5.TIMEFRAME_D1  if MT5_AVAILABLE else 1440,
}


class MT5Connector:
    """
    Wrapper per la connessione e il fetch dati da MT5.
    """

    def __init__(self):
        if not MT5_AVAILABLE:
            raise ImportError(
                "MetaTrader5 non installato.\n"
                "Installa con: pip install MetaTrader5\n"
                "Nota: funziona solo su Windows con MT5 installato."
            )
        self.connected = False

    def connect(self) -> bool:
        """Inizializza la connessione a MT5."""
        # Prova prima senza credenziali (terminale già aperto e loggato)
        ok = mt5.initialize()
        if not ok:
            # Fallback con credenziali esplicite
            mt5_login = int(config.MT5_ACCOUNT) if config.MT5_ACCOUNT else None
            ok = mt5.initialize(
                login=mt5_login,
                password=config.MT5_PASSWORD,
                server=config.MT5_SERVER,
            )
        if not ok:
            error = mt5.last_error()
            logger.error(f"[MT5] Connessione fallita: {error}")
            return False

        info = mt5.account_info()
        if info is None:
            logger.error("[MT5] Impossibile recuperare info account")
            return False

        self.connected = True
        logger.info(
            f"[MT5] Connesso: account={info.login} "
            f"server={info.server} balance={info.balance:.2f}"
        )
        return True

    def disconnect(self):
        if self.connected:
            mt5.shutdown()
            self.connected = False
            logger.info("[MT5] Disconnesso")

    def get_account_balance(self) -> float:
        info = mt5.account_info()
        return info.balance if info else 0.0

    def get_account_equity(self) -> float:
        info = mt5.account_info()
        return info.equity if info else 0.0

    # ── DATI STORICI ──────────────────────────────────────────────────────────

    def get_ohlcv(
        self,
        symbol: str,
        timeframe: str = "M5",
        n_candles: int = 200,
    ) -> Optional[pd.DataFrame]:
        """
        Recupera le ultime n_candles dal simbolo richiesto.
        Ritorna DataFrame con colonne: open, high, low, close, volume.
        """
        if not self.connected:
            logger.error("[MT5] Non connesso. Chiama connect() prima.")
            return None

        tf = TIMEFRAME_MAP.get(timeframe)
        if tf is None:
            logger.error(f"[MT5] Timeframe non supportato: {timeframe}")
            return None

        # Verifica che il simbolo sia disponibile
        if not mt5.symbol_select(symbol, True):
            logger.error(f"[MT5] Simbolo non trovato o non selezionabile: {symbol}")
            return None

        rates = mt5.copy_rates_from_pos(symbol, tf, 0, n_candles)
        if rates is None or len(rates) == 0:
            logger.error(f"[MT5] Nessun dato per {symbol}")
            return None

        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s")
        df = df.set_index("time")
        df = df.rename(columns={
            "open":     "open",
            "high":     "high",
            "low":      "low",
            "close":    "close",
            "tick_volume": "volume",
        })
        df = df[["open", "high", "low", "close", "volume"]]
        return df

    def get_open_positions(self, symbol: str = None) -> list:
        """Recupera le posizioni aperte."""
        if symbol:
            positions = mt5.positions_get(symbol=symbol)
        else:
            positions = mt5.positions_get()
        return list(positions) if positions else []

    def get_open_positions_full(self) -> list[dict]:
        """Restituisce le posizioni aperte con tutti i dati necessari alla dashboard."""
        positions = mt5.positions_get()
        if not positions:
            return []
        result = []
        for p in positions:
            result.append({
                "symbol":      p.symbol,
                "direction":   "long" if p.type == 0 else "short",
                "lot_size":    p.volume,
                "entry_price": p.price_open,
                "sl":          p.sl,
                "tp":          p.tp,
                "pnl":         round(p.profit, 2),
                "open_time":   datetime.fromtimestamp(p.time).isoformat(),
                "ticket":      p.ticket,
            })
        return result

    def get_closed_deals_today(self) -> list[dict]:
        """
        Restituisce i deal di chiusura eseguiti oggi (DEAL_ENTRY_OUT = 1).
        Usa mt5.history_deals_get() con intervallo da mezzanotte a ora corrente.
        """
        from datetime import date, time as dtime
        today_start = datetime.combine(date.today(), dtime(0, 0, 0))
        now         = datetime.now()
        deals = mt5.history_deals_get(today_start, now)
        if not deals:
            return []
        result = []
        for d in deals:
            if d.entry != 1:   # 1 = DEAL_ENTRY_OUT (chiusura)
                continue
            result.append({
                "symbol":     d.symbol,
                "direction":  "long" if d.type == 1 else "short",  # type=1 sell=chiusura long
                "lot_size":   d.volume,
                "entry_price": None,
                "sl":          None,
                "tp":          None,
                "pnl":         round(d.profit + d.commission + d.swap, 2),
                "close_time":  datetime.fromtimestamp(d.time).isoformat(),
                "result":      "win" if (d.profit + d.commission + d.swap) > 0 else "loss",
                "ticket":      d.ticket,
            })
        return result

    def get_symbol_info(self, symbol: str):
        return mt5.symbol_info(symbol)

    def get_tick(self, symbol: str):
        return mt5.symbol_info_tick(symbol)
