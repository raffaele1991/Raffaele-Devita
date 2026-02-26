"""
Precision Comparison Backtest
==============================
Testa 6 configurazioni per trovare la combinazione ottimale di win rate:

  A – Solo SMC             : baseline assoluto (no filtri)
  B – ML 0.42              : filtro ML attivo (threshold corrente)
  C – ML 0.42 + FVG        : solo OB con Fair Value Gap confluente
  D – ML 0.42 + Liq Sweep  : solo OB dopo sweep di liquidità
  E – ML 0.42 + FVG + Liq  : entrambe le confluenze (massima selectività)
  F – ML 0.42 + FVG + HTF  : FVG + allineamento trend M30 (EMA120/300)

Periodo out-of-sample: da TRAIN_CUTOFF_DATE (2026-01-01) in poi.

Uso:
    python precision_comparison.py [SYMBOL] [START_DATE] [END_DATE]
"""

import sys
import os
import logging

logging.disable(logging.CRITICAL)

ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from trading_system.backtest.engine import run_backtest
from trading_system import config


CONFIGS = [
    {
        "label":          "A – Solo SMC",
        "use_ml":         False,
        "ml_threshold":   None,
        "htf_filter":     False,
        "require_fvg":    False,
        "require_liq":    False,
    },
    {
        "label":          "B – ML 0.42",
        "use_ml":         True,
        "ml_threshold":   0.42,
        "htf_filter":     False,
        "require_fvg":    False,
        "require_liq":    False,
    },
    {
        "label":          "C – ML + FVG",
        "use_ml":         True,
        "ml_threshold":   0.42,
        "htf_filter":     False,
        "require_fvg":    True,
        "require_liq":    False,
    },
    {
        "label":          "D – ML + Liq Sweep",
        "use_ml":         True,
        "ml_threshold":   0.42,
        "htf_filter":     False,
        "require_fvg":    False,
        "require_liq":    True,
    },
    {
        "label":          "E – ML + FVG + Liq",
        "use_ml":         True,
        "ml_threshold":   0.42,
        "htf_filter":     False,
        "require_fvg":    True,
        "require_liq":    True,
    },
    {
        "label":          "F – ML + FVG + HTF",
        "use_ml":         True,
        "ml_threshold":   0.42,
        "htf_filter":     True,
        "require_fvg":    True,
        "require_liq":    False,
    },
    {
        "label":          "G – ML + Liq + HTF",
        "use_ml":         True,
        "ml_threshold":   0.42,
        "htf_filter":     True,
        "require_fvg":    False,   # FVG quasi assente su forex (EURUSD ~2%)
        "require_liq":    True,    # Liq sweep abbondante su forex (~96%)
    },
]


def run_config(cfg: dict, symbol: str, start: str, end: str) -> dict:
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
            require_fvg=cfg["require_fvg"],
            require_liq_sweep=cfg["require_liq"],
        )
    except Exception as e:
        result = {"error": str(e)}
    finally:
        config.USE_ML_FILTER = original_ml
    return result


def print_table(results: list, configs: list) -> None:
    n_cols = len(configs)
    W = 20

    header_labels = [c["label"] for c in configs]
    sep = "─" * (W + 3 + W * n_cols + (n_cols - 1) * 3)

    symbol = results[0].get("symbol", "?") if results and "error" not in results[0] else "?"
    sd     = results[0].get("start_date", "?") if results and "error" not in results[0] else "?"
    ed     = results[0].get("end_date",   "?") if results and "error" not in results[0] else "?"

    print(f"\n{'═' * len(sep)}")
    print(f"  CONFRONTO WIN RATE – {symbol}  {sd} → {ed}")
    print(f"{'═' * len(sep)}")

    hdr = f"{'Metrica':<{W}} | " + " | ".join(h.rjust(W) for h in header_labels)
    print(hdr)
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
        ("Max Drawdown",    "max_dd_pct",    "{:.2f}",  "%"),
        ("Sharpe",          "sharpe",        "{:.2f}",  ""),
        ("Net P&L %",       "net_pnl_pct",   "{:+.2f}", "%"),
    ]

    for label, key, fmt, suffix in rows:
        vals = [v(r, key, fmt, suffix).rjust(W) for r in results]
        print(f"{label:<{W}} | " + " | ".join(vals))

    print(sep)

    for i, (cfg, res) in enumerate(zip(configs, results)):
        if "error" in res:
            print(f"  [!] {cfg['label']}: {res['error']}")
    print()


def print_summary(results: list, configs: list) -> None:
    baseline = results[0]
    if "error" in baseline:
        return

    base_wr = baseline.get("win_rate", 0)
    base_n  = baseline.get("n_trades", 0)

    print("── DELTA vs Config A (Solo SMC) ─────────────────────────────────────────")
    print(f"  {'Config':<35} {'WR delta':>10}  {'Trade':>7}  {'PF':>6}  {'Net%':>8}")
    print(f"  {'─'*35} {'─'*10}  {'─'*7}  {'─'*6}  {'─'*8}")
    for cfg, res in zip(configs[1:], results[1:]):
        if "error" in res:
            print(f"  {cfg['label']:<35} ERRORE")
            continue
        wr_d  = res.get("win_rate", 0) - base_wr
        n     = res.get("n_trades", 0)
        pf    = res.get("profit_factor", 0)
        netp  = res.get("net_pnl_pct", 0)
        arrow = "▲" if wr_d > 0.5 else ("▼" if wr_d < -0.5 else "~")
        print(f"  {cfg['label']:<35} {arrow}{wr_d:+.1f}pp    {n:>6}   {pf:>5.2f}  {netp:>+7.2f}%")
    print()

    # Trova miglior win rate con almeno 20 trade
    best_wr  = -1
    best_pf  = -1
    best_cfg_wr  = None
    best_cfg_pf  = None
    for cfg, res in zip(configs, results):
        if "error" not in res and res.get("n_trades", 0) >= 20:
            if res.get("win_rate", 0) > best_wr:
                best_wr  = res.get("win_rate", 0)
                best_cfg_wr = cfg["label"]
            if res.get("profit_factor", 0) > best_pf:
                best_pf  = res.get("profit_factor", 0)
                best_cfg_pf = cfg["label"]

    if best_cfg_wr:
        print(f"→ Miglior Win Rate (≥20 trade): {best_cfg_wr}  WR={best_wr:.1f}%")
    if best_cfg_pf and best_cfg_pf != best_cfg_wr:
        print(f"→ Miglior Profit Factor        : {best_cfg_pf}  PF={best_pf:.2f}")
    print()


if __name__ == "__main__":
    symbol     = sys.argv[1] if len(sys.argv) > 1 else "XAUUSD"
    start_date = sys.argv[2] if len(sys.argv) > 2 else config.TRAIN_CUTOFF_DATE
    end_date   = sys.argv[3] if len(sys.argv) > 3 else "2026-02-25"

    print(f"\nPrecision & Win Rate Comparison Backtest")
    print(f"Simbolo : {symbol}")
    print(f"Periodo : {start_date} → {end_date}  (out-of-sample)")
    print(f"Balance : $10,000")
    print()

    results = []
    for cfg in CONFIGS:
        print(f"  {cfg['label']}...", end="", flush=True)
        res = run_config(cfg, symbol, start_date, end_date)
        results.append(res)
        if "error" in res:
            print(f" ERRORE: {res['error']}")
        else:
            n  = res.get("n_trades", 0)
            wr = res.get("win_rate", 0)
            pf = res.get("profit_factor", 0)
            print(f" {n} trade  WR={wr:.1f}%  PF={pf:.2f}")

    print_table(results, CONFIGS)
    print_summary(results, CONFIGS)
