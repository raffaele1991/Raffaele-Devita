"""
Risk Manager – Prop Firm Compliant
=====================================
Gestisce sizing, drawdown e protezione del conto.
Tutte le regole sono calibrate per passare la fase di evaluation FTMO/MyFundedFX.
"""

import logging
from datetime import datetime, date
from dataclasses import dataclass, field
from typing import Optional
from trading_system import config

logger = logging.getLogger(__name__)


@dataclass
class TradeRecord:
    symbol:    str
    direction: str
    entry:     float
    sl:        float
    tp:        float
    lot_size:  float
    open_time: datetime
    pnl:       Optional[float] = None
    close_time: Optional[datetime] = None
    result:    str = "open"  # "open", "win", "loss"


class RiskManager:
    """
    Calcola il lot size, verifica i limiti di drawdown e tiene
    traccia dello stato giornaliero del conto.
    """

    def __init__(self, account_balance: float):
        self.initial_balance     = account_balance
        self.current_balance     = account_balance
        self.current_equity      = account_balance   # equity MT5 (include floating P&L)

        self.daily_start_balance: float = account_balance
        self.daily_start_date:    date  = date.today()

        # ── DD stile FTMO: massimo raggiunto, si aggiorna solo al rialzo ──────
        # Il DD registrato NON scende quando l'equity recupera — rispecchia
        # esattamente come le prop calcolano il limite giornaliero/totale.
        self.max_daily_dd_pct:  float = 0.0   # reset ogni giorno
        self.max_total_dd_pct:  float = 0.0   # mai resettato

        self.trades_today:         int  = 0
        self.consecutive_losses:   int  = 0
        self.open_trades:          list = []
        self.closed_trades:        list = []

    # ── AGGIORNAMENTO SALDO / EQUITY ──────────────────────────────────────────

    def update_balance(self, new_balance: float):
        """Chiama ogni volta che il saldo MT5 cambia."""
        self.current_balance = new_balance

        # Reset giornaliero
        today = date.today()
        if today != self.daily_start_date:
            self.daily_start_balance = new_balance
            self.daily_start_date    = today
            self.max_daily_dd_pct    = 0.0
            self.trades_today        = 0
            self.consecutive_losses  = 0
            logger.info("[Risk] Reset giornaliero contatori")

    def update_equity(self, new_equity: float):
        """Chiama ogni ciclo con l'equity MT5 (balance + floating P&L).
        Aggiorna il massimo DD giornaliero e totale stile FTMO:
        il valore cresce quando il DD peggiora, ma NON scende al recupero."""
        self.current_equity = new_equity

        daily_dd = (self.daily_start_balance - new_equity) / self.daily_start_balance
        total_dd = (self.initial_balance     - new_equity) / self.initial_balance

        # Aggiorna SOLO se il nuovo DD è peggiorativo (più alto)
        if daily_dd > self.max_daily_dd_pct:
            self.max_daily_dd_pct = daily_dd
            logger.debug(f"[Risk] Nuovo max DD giornaliero: {daily_dd*100:.2f}%")

        if total_dd > self.max_total_dd_pct:
            self.max_total_dd_pct = total_dd
            logger.debug(f"[Risk] Nuovo max DD totale: {total_dd*100:.2f}%")

    # ── CONTROLLO LIMITI ──────────────────────────────────────────────────────

    def can_trade(self) -> tuple[bool, str]:
        """
        Ritorna (True, "") se il bot può aprire nuovi trade.
        Ritorna (False, motivo) se deve fermarsi.
        """
        # Limite trade giornalieri
        if self.trades_today >= config.PROP_MAX_TRADES_PER_DAY:
            return False, f"Limite trade giornalieri raggiunto ({config.PROP_MAX_TRADES_PER_DAY})"

        # Limite perdite consecutive
        if self.consecutive_losses >= config.MAX_CONSECUTIVE_LOSSES:
            return False, f"Stop: {config.MAX_CONSECUTIVE_LOSSES} stop loss consecutivi"

        # Drawdown giornaliero — stile FTMO: usa il MASSIMO raggiunto oggi,
        # anche se l'equity ha recuperato in seguito.
        if self.max_daily_dd_pct >= config.PROP_MAX_DAILY_LOSS_PCT:
            return False, (f"Daily drawdown limit: {self.max_daily_dd_pct*100:.2f}% "
                           f">= {config.PROP_MAX_DAILY_LOSS_PCT*100:.1f}%")

        # Drawdown totale — stessa logica: massimo storico mai raggiunto.
        if self.max_total_dd_pct >= config.PROP_MAX_TOTAL_LOSS_PCT:
            return False, (f"Total drawdown limit: {self.max_total_dd_pct*100:.2f}% "
                           f">= {config.PROP_MAX_TOTAL_LOSS_PCT*100:.1f}%")

        return True, ""

    # ── LOT SIZE ──────────────────────────────────────────────────────────────

    def calculate_lot_size(
        self,
        symbol: str,
        entry_price: float,
        sl_price: float,
        pip_value: float = None,
    ) -> float:
        """
        Calcola il lot size in base al rischio % configurato.

        pip_value: valore di 1 pip per 1 lotto standard (USD)
                   XAUUSD: 1 pip = $1 per 1 oz lot (100 oz = $100)
                   EURUSD: 1 pip = $10 per lotto standard
        """
        risk_amount = self.current_balance * config.RISK_PER_TRADE_PCT
        sl_distance = abs(entry_price - sl_price)

        if pip_value is None:
            # Valori di default per i simboli supportati
            if "XAU" in symbol:
                # Gold: 1 lotto = 100 oz, 1 pip = $0.01 = $1 per lotto
                pip_value = 1.0
                sl_pips   = sl_distance / 0.01   # 1 pip Gold = $0.01
            elif "JPY" in symbol:
                # Coppie JPY: 1 pip = 0.01; pip value in USD = (0.01 × 100.000) / prezzo
                pip_size  = 0.01
                pip_value = (pip_size * 100_000) / entry_price  # ~6.4 USD/lotto a ~156
                sl_pips   = sl_distance / pip_size
            else:
                # Forex USD-quoted (EURUSD, GBPUSD…): 1 pip = 0.0001 = $10/lotto
                pip_value = 10.0
                sl_pips   = sl_distance / 0.0001

        else:
            # pip_value fornito dall'esterno: adatta pip_size al simbolo
            pip_size = 0.01 if "JPY" in symbol else 0.0001
            sl_pips  = sl_distance / pip_size

        if sl_pips <= 0:
            return 0.01  # minimo sicuro

        lot_size = risk_amount / (sl_pips * pip_value)

        # Limiti di sicurezza
        lot_size = round(lot_size, 2)
        lot_size = max(0.01, min(lot_size, 5.0))

        return lot_size

    # ── RECORD TRADES ─────────────────────────────────────────────────────────

    def register_trade_open(self, trade: TradeRecord):
        self.open_trades.append(trade)
        self.trades_today += 1
        logger.info(
            f"[Risk] Trade aperto: {trade.symbol} {trade.direction.upper()} "
            f"lot={trade.lot_size} | Trade oggi: {self.trades_today}"
        )

    def register_trade_close(self, trade: TradeRecord, pnl: float):
        trade.pnl        = pnl
        trade.close_time = datetime.now()
        trade.result     = "win" if pnl > 0 else "loss"

        if trade in self.open_trades:
            self.open_trades.remove(trade)
        self.closed_trades.append(trade)

        if pnl > 0:
            self.consecutive_losses = 0
            logger.info(f"[Risk] Trade chiuso WIN: +{pnl:.2f}")
        else:
            self.consecutive_losses += 1
            logger.warning(
                f"[Risk] Trade chiuso LOSS: {pnl:.2f} | "
                f"Perdite consecutive: {self.consecutive_losses}"
            )

        self.current_balance += pnl

    # ── STATISTICHE ───────────────────────────────────────────────────────────

    def status(self) -> dict:
        # DD corrente (momentaneo — mostra la situazione live)
        daily_dd_now = max(0.0, (self.daily_start_balance - self.current_equity) / self.daily_start_balance)
        total_dd_now = max(0.0, (self.initial_balance     - self.current_equity) / self.initial_balance)

        # P&L giornaliero in $ e %
        daily_pnl     = self.current_equity - self.daily_start_balance
        daily_pnl_pct = daily_pnl / self.daily_start_balance * 100

        wins      = sum(1 for t in self.closed_trades if t.result == "win")
        losses    = sum(1 for t in self.closed_trades if t.result == "loss")
        win_rate  = wins / max(wins + losses, 1) * 100

        return {
            "balance":              self.current_balance,
            "equity":               self.current_equity,
            # max_*: quello che la prop registra — non scende al recupero
            "daily_drawdown_pct":   round(self.max_daily_dd_pct * 100, 2),
            "total_drawdown_pct":   round(self.max_total_dd_pct * 100, 2),
            # current_*: DD live (può migliorare se si recupera)
            "daily_dd_now_pct":     round(daily_dd_now * 100, 2),
            "total_dd_now_pct":     round(total_dd_now * 100, 2),
            "daily_pnl":            round(daily_pnl, 2),
            "daily_pnl_pct":        round(daily_pnl_pct, 2),
            "trades_today":         self.trades_today,
            "consecutive_losses":   self.consecutive_losses,
            "total_wins":           wins,
            "total_losses":         losses,
            "win_rate":             round(win_rate, 1),
            "open_positions":       len(self.open_trades),
        }
