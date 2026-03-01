"""
Filter Optimizer – Grid Search su tutti i filtri disponibili
=============================================================
Testa ogni combinazione di:
  • FVG required          (True / False)
  • Liq Sweep required    (True / False)
  • HTF alignment         (True / False)
  • PA filter             (True / False)
  • ML min confidence     (lista soglie)
  • ML max confidence     (None = nessun tetto | 0.85 = blocca ≥0.85)

Per ogni combinazione esegue run_backtest in modalità quiet e raccoglie:
  Trade, WR%, Avg Win R, Avg Loss R, Profit Factor, Net R, MaxDD, Sharpe

Output: tabella ordinata per Net R decrescente.

Uso:
    python -m trading_system.backtest.optimize --symbol XAUUSD \
        --start 2026-01-01 --end 2026-02-28
"""

import argparse
import itertools
import sys
import os
import traceback

# ── percorso root ─────────────────────────────────────────────────────────────
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from trading_system.backtest.engine import run_backtest

# ── Parametri del grid search ─────────────────────────────────────────────────

GRID = {
    "require_fvg":       [True, False],
    "require_liq_sweep": [True, False],
    "htf_hard_filter":   [True, False],
    "require_pa":        [True, False],
    "ml_threshold":      [0.62, 0.65, 0.70],
    "ml_confidence_max": [None, 0.85],   # None = nessun tetto superiore
}

MIN_TRADES = 10   # salta combinazioni con meno di N trade (troppo pochi per essere significativi)


def _label(val) -> str:
    if val is None:
        return " — "
    if isinstance(val, bool):
        return "✓" if val else "✗"
    return str(val)


def run_grid(symbol: str, start: str, end: str, top_n: int = 20) -> None:
    keys   = list(GRID.keys())
    values = list(GRID.values())
    combos = list(itertools.product(*values))

    total  = len(combos)
    print(f"\nGrid search {symbol}: {total} combinazioni da testare…\n")

    results = []
    for idx, combo in enumerate(combos, 1):
        params = dict(zip(keys, combo))
        print(f"  [{idx:>3}/{total}] FVG={_label(params['require_fvg'])} "
              f"LIQ={_label(params['require_liq_sweep'])} "
              f"HTF={_label(params['htf_hard_filter'])} "
              f"PA={_label(params['require_pa'])} "
              f"ML≥{params['ml_threshold']} "
              f"ML<{params['ml_confidence_max'] or '—':>4}", end="  … ", flush=True)

        try:
            res = run_backtest(
                symbol=symbol,
                start_date=start,
                end_date=end,
                ml_threshold=params["ml_threshold"],
                ml_confidence_max=params["ml_confidence_max"],
                htf_hard_filter=params["htf_hard_filter"],
                require_fvg=params["require_fvg"],
                require_liq_sweep=params["require_liq_sweep"],
                require_pa=params["require_pa"],
                quiet=True,
            )
            n = res.get("n_trades", 0)
            if n < MIN_TRADES:
                print(f"skip ({n} trade < {MIN_TRADES})")
                continue

            results.append({**params, **res})
            print(f"OK  {n:>3}tr  WR={res['win_rate']:>5.1f}%  "
                  f"NetR={res.get('net_r', 0):>+.1f}  PF={res['profit_factor']:.2f}")

        except Exception as e:
            print(f"ERR ({e})")

    if not results:
        print("\nNessun risultato valido.")
        return

    # ── Ordina per Net R decrescente ──────────────────────────────────────────
    results.sort(key=lambda r: r.get("net_r", 0), reverse=True)

    # ── Stampa tabella classifica ─────────────────────────────────────────────
    SEP = "─" * 110
    print(f"\n{'═' * 110}")
    print(f"  CLASSIFICA OTTIMIZZAZIONE FILTRI  –  {symbol}  [{start} → {end}]")
    print(f"{'═' * 110}")
    print(f"  {'#':>3}  {'FVG':<4} {'LIQ':<4} {'HTF':<4} {'PA':<4} "
          f"{'ML≥':<6} {'ML<':<6} "
          f"{'Tr':>4} {'WR%':>6} {'AvgW':>6} {'AvgL':>6} "
          f"{'PF':>5} {'NetR':>7} {'MaxDD':>7} {'Sharpe':>7}")
    print(f"  {SEP}")

    for rank, r in enumerate(results[:top_n], 1):
        ml_max_str = f"{r['ml_confidence_max']:.2f}" if r['ml_confidence_max'] else "  — "
        net_r      = r.get("net_r", 0)
        flag = " ◄ BEST" if rank == 1 else ""
        print(
            f"  {rank:>3}  "
            f"{_label(r['require_fvg']):<4} "
            f"{_label(r['require_liq_sweep']):<4} "
            f"{_label(r['htf_hard_filter']):<4} "
            f"{_label(r['require_pa']):<4} "
            f"{r['ml_threshold']:<6.2f} "
            f"{ml_max_str:<6} "
            f"{r['n_trades']:>4} "
            f"{r['win_rate']:>5.1f}% "
            f"{r.get('avg_win_r', 0):>+5.2f}R "
            f"{r.get('avg_loss_r', 0):>+5.2f}R "
            f"{r['profit_factor']:>5.2f} "
            f"{net_r:>+6.2f}R "
            f"{r.get('max_dd_pct', 0):>6.1f}% "
            f"{r.get('sharpe', 0):>7.2f}"
            f"{flag}"
        )

    print(f"  {SEP}")
    print(f"\n  Top 1 configurazione:")
    best = results[0]
    print(f"    FVG={_label(best['require_fvg'])}  LIQ={_label(best['require_liq_sweep'])}  "
          f"HTF={_label(best['htf_hard_filter'])}  PA={_label(best['require_pa'])}  "
          f"ML=[{best['ml_threshold']:.2f}, {best['ml_confidence_max'] or '∞'})")
    print(f"    Trade={best['n_trades']}  WR={best['win_rate']:.1f}%  "
          f"NetR={best.get('net_r', 0):+.2f}R  PF={best['profit_factor']:.2f}  "
          f"MaxDD={best.get('max_drawdown', 0):.1f}%  Sharpe={best.get('sharpe', 0):.2f}")
    print()


def main() -> None:
    parser = argparse.ArgumentParser(description="Grid search filtri backtest")
    parser.add_argument("--symbol", default="XAUUSD")
    parser.add_argument("--start",  default="2026-01-01")
    parser.add_argument("--end",    default="2026-02-28")
    parser.add_argument("--top",    type=int, default=20, help="quante righe mostrare")
    args = parser.parse_args()

    run_grid(symbol=args.symbol, start=args.start, end=args.end, top_n=args.top)


if __name__ == "__main__":
    main()
