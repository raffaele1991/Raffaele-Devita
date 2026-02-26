"""
Precision Comparison Backtest
==============================
Testa 4 configurazioni per confrontare l'impatto sulla Precision:

  Config A – Solo SMC (no ML)           : baseline assoluto
  Config B – ML threshold 0.42 (attuale): baseline con ML corretto
  Config C – ML threshold 0.52 (alzata) : meno trade, più precision
  Config D – ML 0.52 + HTF hard filter  : massima selectività

Periodo out-of-sample: da TRAIN_CUTOFF_DATE (2026-01-01) in poi.
Simbolo di default: XAUUSD (usa più segnali SMC, confronto più ricco).

Uso:
    python precision_comparison.py [SYMBOL] [START_DATE] [END_DATE]

Esempi:
    python precision_comparison.py
    python precision_comparison.py XAUUSD 2026-01-01 2026-02-25
    python precision_comparison.py EURUSD 2025-06-01 2025-12-31
"""

import sys
import os
import logging

# Silenzia i log del motore durante il confronto (riduce rumore)
logging.disable(logging.CRITICAL)

ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from trading_system.backtest.engine import run_backtest
from trading_system import config


# ── CONFIGURAZIONI DA TESTARE ─────────────────────────────────────────────────

CONFIGS = [
    {
        "label":          "A – Solo SMC",
        "use_ml":         False,
        "ml_threshold":   None,
        "htf_filter":     False,
        "description":    "Nessun filtro ML – solo segnali SMC puri",
    },
    {
        "label":          "B – ML 0.42 (attuale, corretto)",
        "use_ml":         True,
        "ml_threshold":   0.42,
        "htf_filter":     False,
        "description":    "Soglia attuale con fix DatetimeIndex",
    },
    {
        "label":          "C – ML 0.52 (alzata)",
        "use_ml":         True,
        "ml_threshold":   0.52,
        "htf_filter":     False,
        "description":    "Soglia più alta: meno trade, più precision",
    },
    {
        "label":          "D – ML 0.52 + HTF hard filter",
        "use_ml":         True,
        "ml_threshold":   0.52,
        "htf_filter":     True,
        "description":    "Max selectività: ML alto + M30 trend obbligatorio",
    },
]


def run_config(cfg: dict, symbol: str, start: str, end: str) -> dict | None:
    """Esegue il backtest per una configurazione e ritorna i risultati."""
    # Override temporaneo USE_ML_FILTER
    original_ml = config.USE_ML_FILTER
    config.USE_ML_FILTER = cfg["use_ml"]

    try:
        result = run_backtest(
            symbol=symbol,
            start_date=start,
            end_date=end,
            initial_balance=10_000.0,
            ml_threshold=cfg["ml_threshold"],
            htf_hard_filter=cfg["htf_filter"],
        )
    except Exception as e:
        result = {"error": str(e)}
    finally:
        config.USE_ML_FILTER = original_ml

    return result


def print_table(results: list[dict], configs: list[dict]) -> None:
    """Stampa tabella comparativa."""
    W = 22  # larghezza colonne

    sep = "─" * (W + 1 + W * 4 + 3)

    print(f"\n{'═' * len(sep)}")
    print(f"  CONFRONTO CONFIGURAZIONI PRECISION – {results[0].get('symbol','?')}  "
          f"{results[0].get('start_date','?')} → {results[0].get('end_date','?')}")
    print(f"{'═' * len(sep)}")

    # Header
    print(f"{'Metrica':<{W}} | {'A – Solo SMC':>{W}} | {'B – ML 0.42':>{W}} | {'C – ML 0.52':>{W}} | {'D – 0.52+HTF':>{W}}")
    print(sep)

    def v(res, key, fmt="{:.1f}", suffix=""):
        if "error" in res:
            return "ERRORE"
        val = res.get(key, "–")
        if isinstance(val, (int, float)):
            return fmt.format(val) + suffix
        return str(val)

    rows = [
        ("Trade totali",    "n_trades",      "{:.0f}",  ""),
        ("Win Rate",        "win_rate",      "{:.1f}",  "%"),
        ("Profit Factor",   "profit_factor", "{:.2f}",  ""),
        ("Net R",           "net_r",         "{:+.1f}", "R"),
        ("Avg Win R",       "avg_win_r",     "{:+.2f}", "R"),
        ("Avg Loss R",      "avg_loss_r",    "{:+.2f}", "R"),
        ("Max Drawdown",    "max_dd_pct",    "{:.2f}",  "%"),
        ("Sharpe",          "sharpe",        "{:.2f}",  ""),
        ("Net P&L %",       "net_pnl_pct",   "{:+.2f}", "%"),
    ]

    for label, key, fmt, suffix in rows:
        vals = [v(r, key, fmt, suffix).rjust(W) for r in results]
        print(f"{label:<{W}} | {' | '.join(vals)}")

    print(sep)

    # Segnala errori
    for i, (cfg, res) in enumerate(zip(configs, results)):
        if "error" in res:
            print(f"  [!] Config {cfg['label']}: {res['error']}")

    print()


def precision_improvement(a: dict, b: dict) -> str:
    """Confronta Win Rate di due configurazioni."""
    if "error" in a or "error" in b:
        return "n/a"
    delta = b.get("win_rate", 0) - a.get("win_rate", 0)
    return f"{delta:+.1f}pp"


def print_summary(results: list[dict], configs: list[dict]) -> None:
    """Stampa un riassunto breve."""
    baseline = results[0]  # Config A
    print("── MIGLIORAMENTO WIN RATE vs baseline (Config A – Solo SMC) ─────────────")
    for cfg, res in zip(configs[1:], results[1:]):
        delta = precision_improvement(baseline, res)
        trades_delta = ""
        if "n_trades" in res and "n_trades" in baseline:
            t_delta = res["n_trades"] - baseline["n_trades"]
            trades_delta = f"  | trade: {t_delta:+d}"
        print(f"  {cfg['label']:<35} WR delta: {delta}{trades_delta}")

    print()
    print("── TRADE COUNT ──────────────────────────────────────────────────────────")
    for cfg, res in zip(configs, results):
        if "error" not in res:
            n = res.get("n_trades", 0)
            wr = res.get("win_rate", 0)
            pf = res.get("profit_factor", 0)
            print(f"  {cfg['label']:<35} {n:>4} trade  WR={wr:.1f}%  PF={pf:.2f}")
    print()


if __name__ == "__main__":
    # Parametri da riga di comando
    symbol     = sys.argv[1] if len(sys.argv) > 1 else "XAUUSD"
    start_date = sys.argv[2] if len(sys.argv) > 2 else config.TRAIN_CUTOFF_DATE
    end_date   = sys.argv[3] if len(sys.argv) > 3 else "2026-02-25"

    print(f"\nPrecision Comparison Backtest")
    print(f"Simbolo : {symbol}")
    print(f"Periodo : {start_date} → {end_date}  (out-of-sample)")
    print(f"Balance : $10,000")
    print()

    results = []
    for cfg in CONFIGS:
        print(f"  Esecuzione {cfg['label']}...", end="", flush=True)
        res = run_config(cfg, symbol, start_date, end_date)
        results.append(res)
        if "error" in res:
            print(f" ERRORE: {res['error']}")
        else:
            print(f" {res.get('n_trades',0)} trade  WR={res.get('win_rate',0):.1f}%")

    print_table(results, CONFIGS)
    print_summary(results, CONFIGS)

    # Consiglio finale
    best = None
    best_pf = -1
    for cfg, res in zip(CONFIGS, results):
        if "error" not in res and res.get("profit_factor", 0) > best_pf:
            best_pf = res.get("profit_factor", 0)
            best = cfg["label"]
    if best:
        print(f"→ Miglior Profit Factor: {best}")
    print()
