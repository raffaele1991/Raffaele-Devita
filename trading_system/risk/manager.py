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
        self.peak_equity         = account_balance

        self.daily_start_balance: float = account_balance
        self.daily_start_date:    date  = date.today()

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
            self.trades_today        = 0
            self.consecutive_losses  = 0
            logger.info("[Risk] Reset giornaliero contatori")

    def update_equity(self, new_equity: float):
        """Chiama ogni ciclo con l'equity MT5 (balance + floating P&L)."""
        self.current_equity = new_equity
        if new_equity > self.peak_equity:
            self.peak_equity = new_equity

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

        # Drawdown giornaliero (su equity — include floating P&L)
        daily_dd = (self.daily_start_balance - self.current_equity) / self.daily_start_balance
        if daily_dd >= config.PROP_MAX_DAILY_LOSS_PCT:
            return False, f"Daily drawdown limit: {daily_dd*100:.2f}% >= {config.PROP_MAX_DAILY_LOSS_PCT*100:.1f}%"

        # Drawdown totale (su equity)
        total_dd = (self.initial_balance - self.current_equity) / self.initial_balance
        if total_dd >= config.PROP_MAX_TOTAL_LOSS_PCT:
            return False, f"Total drawdown limit: {total_dd*100:.2f}% >= {config.PROP_MAX_TOTAL_LOSS_PCT*100:.1f}%"

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
            else:
                # Forex: 1 lotto standard = 100,000 unità
                pip_value = 10.0
                sl_pips   = sl_distance / 0.0001  # 1 pip Forex = 0.0001

        else:
            sl_pips = sl_distance / 0.0001

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
        # DD su equity (standard prop firm): clampato a 0 se in profitto
        daily_dd = max(0.0, (self.daily_start_balance - self.current_equity) / self.daily_start_balance)
        total_dd = max(0.0, (self.initial_balance     - self.current_equity) / self.initial_balance)

        # P&L giornaliero in $ e %
        daily_pnl     = self.current_equity - self.daily_start_balance
        daily_pnl_pct = daily_pnl / self.daily_start_balance * 100

        wins      = sum(1 for t in self.closed_trades if t.result == "win")
        losses    = sum(1 for t in self.closed_trades if t.result == "loss")
        win_rate  = wins / max(wins + losses, 1) * 100

        return {
            "balance":            self.current_balance,
            "equity":             self.current_equity,
            "daily_drawdown_pct": round(daily_dd * 100, 2),
            "total_drawdown_pct": round(total_dd * 100, 2),
            "daily_pnl":          round(daily_pnl, 2),
            "daily_pnl_pct":      round(daily_pnl_pct, 2),
            "trades_today":       self.trades_today,
            "consecutive_losses": self.consecutive_losses,
            "total_wins":         wins,
            "total_losses":       losses,
            "win_rate":           round(win_rate, 1),
            "open_positions":     len(self.open_trades),
        }
