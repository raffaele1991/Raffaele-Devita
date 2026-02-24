"""
Backtest Engine – SMC + ML
===========================
Replica esattamente la logica del bot live su dati storici CSV:
  1. Finestra di contesto scorrevole (ultimi 200 bar)
  2. Rilevamento segnale SMC (BOS/CHoCH + Order Block + FVG)
  3. Conferma ML (se il modello .pkl è disponibile)
  4. Filtro sessione (London 08-11 / NY 14-17 ora broker)
  5. Simulazione esito: SL o TP colpito entro MAX_HOLD candele
  6. Metriche: win rate, profit factor, net R, max DD, Sharpe

Avvio dal dashboard → POST /api/backtest
Stato in tempo reale → GET  /api/backtest/status
"""

import os
import sys
import copy
import threading
import numpy as np
import pandas as pd
from datetime import time as dtime
from typing import Optional, Dict, Any

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from trading_system.smc.detector import SMCDetector
from trading_system.smc.structure import detect_structure
from trading_system.ml.features import build_features
from trading_system.ml.model import SMCMLModel
from trading_system import config


# ── GLOBAL STATE ──────────────────────────────────────────────────────────────

_lock = threading.Lock()
_state: Dict[str, Any] = {
    "running":  False,
    "progress": 0,
    "status":   "idle",   # idle | running | done | error
    "results":  None,
    "error":    None,
    "log":      [],
}


def _log(msg: str) -> None:
    from datetime import datetime
    line = f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"
    print(line)
    with _lock:
        _state["log"].append(line)
        if len(_state["log"]) > 500:
            _state["log"] = _state["log"][-500:]


# ── FILTRO SESSIONE (su timestamp storico) ────────────────────────────────────

def _in_session(ts: pd.Timestamp) -> bool:
    """
    Verifica se la candela cade in una kill zone.
    I dati MT5 sono in ora broker (solitamente UTC+2/+3, simile a CET/CEST).
    Usiamo direttamente l'ora del timestamp senza conversione timezone.
    London: 08:00–11:00 | NY: 14:00–17:00
    """
    try:
        h = ts.hour
        in_london = 8 <= h < 11
        in_ny     = 14 <= h < 17
        return in_london or in_ny
    except Exception:
        return True


# ── CSV LOADER ────────────────────────────────────────────────────────────────

def _load_csv(symbol: str) -> pd.DataFrame:
    data_dir = os.path.join(os.path.dirname(__file__), '..', 'data')
    path = os.path.join(data_dir, f"{symbol}_M5.csv")

    if not os.path.exists(path):
        raise FileNotFoundError(
            f"CSV non trovato: {symbol}_M5.csv\n"
            f"Scarica prima i dati dalla sezione 'Dati Storici MT5' della dashboard."
        )

    # Prova diversi separatori
    df = None
    for sep in ['\t', ',', ';']:
        try:
            tmp = pd.read_csv(path, sep=sep, engine='python')
            if len(tmp.columns) >= 5:
                df = tmp
                break
        except Exception:
            continue

    if df is None:
        raise ValueError(f"Impossibile leggere il CSV: {path}")

    # Normalizza nomi colonne (strip whitespace + parentesi angolari MT5: <OPEN> → open)
    df.columns = [c.strip().strip('<>').lower() for c in df.columns]

    # Trova colonna tempo
    time_col = None
    for c in ['time', 'datetime', 'timestamp']:
        if c in df.columns:
            time_col = c
            break

    # Formato MT5: colonne "date" e "time" separate
    if time_col is None:
        if 'date' in df.columns and 'time' in df.columns:
            df['_dt'] = df['date'].astype(str) + ' ' + df['time'].astype(str)
            time_col = '_dt'
        elif 'date' in df.columns:
            time_col = 'date'
        else:
            time_col = df.columns[0]

    df['time'] = pd.to_datetime(df[time_col], errors='coerce')

    # Mappa OHLCV
    rename = {}
    for c in df.columns:
        if c in ('open', 'o'):                          rename[c] = 'open'
        elif c in ('high', 'h'):                        rename[c] = 'high'
        elif c in ('low', 'l'):                         rename[c] = 'low'
        elif c in ('close', 'c'):                       rename[c] = 'close'
        elif c in ('volume', 'vol', 'tickvol',
                   'tick_volume', 'real_volume'):        rename[c] = 'volume'
    df = df.rename(columns=rename)

    needed = ['time', 'open', 'high', 'low', 'close']
    missing = [c for c in needed if c not in df.columns]
    if missing:
        raise ValueError(f"Colonne mancanti nel CSV {symbol}: {missing}")

    cols = needed + (['volume'] if 'volume' in df.columns else [])
    df = df[cols].copy()

    for c in ['open', 'high', 'low', 'close']:
        df[c] = pd.to_numeric(df[c], errors='coerce')

    df = df.dropna(subset=['time', 'open', 'high', 'low', 'close'])
    df = df.sort_values('time').reset_index(drop=True)
    return df


# ── CORE ENGINE ───────────────────────────────────────────────────────────────

def run_backtest(
    symbol: str,
    start_date: str,
    end_date: str,
    initial_balance: float = 10_000.0,
) -> Dict[str, Any]:

    _log(f"{'=' * 50}")
    _log(f"  BACKTEST {symbol}")
    _log(f"  Periodo: {start_date} → {end_date}")
    _log(f"{'=' * 50}")

    # 1. Carica e filtra CSV per data
    _log("Caricamento dati CSV...")
    df = _load_csv(symbol)

    start_dt = pd.to_datetime(start_date)
    end_dt   = pd.to_datetime(end_date) + pd.Timedelta(days=1)
    mask     = (df['time'] >= start_dt) & (df['time'] < end_dt)
    df       = df[mask].reset_index(drop=True)

    if len(df) < 100:
        raise ValueError(
            f"Dati insufficienti: solo {len(df)} candele nel periodo selezionato. "
            f"Allarga l'intervallo o scarica più storico."
        )

    _log(f"Candele caricate : {len(df):,}")
    _log(f"Da               : {df['time'].iloc[0]}")
    _log(f"A                : {df['time'].iloc[-1]}")

    # 2. Carica modello ML (opzionale)
    ml_model: Optional[SMCMLModel] = None
    model_path = os.path.join(
        os.path.dirname(__file__), '..', 'models',
        f"model_{symbol.lower()}.pkl"
    )
    if os.path.exists(model_path):
        try:
            ml_model = SMCMLModel(symbol)
            ml_model.load()
            _log(f"Modello ML caricato ✓")
        except Exception as e:
            _log(f"Avviso ML: {e} → procedo solo con SMC")
            ml_model = None
    else:
        _log("Modello ML non trovato → backtest solo SMC (senza filtro ML)")

    # 3. Parametri
    detector = SMCDetector(symbol)
    MIN_LB   = 80    # candele di lookback minimo prima di iniziare
    MAX_HOLD = 40    # candele massime per tenere una posizione aperta
    CONTEXT  = 200   # dimensione finestra scorrevole

    trades     = []
    balance    = initial_balance
    max_equity = initial_balance
    max_dd_pct = 0.0
    i          = MIN_LB

    _log(f"Avvio simulazione...")

    while i < len(df):
        # Aggiorna progresso globale
        with _lock:
            _state["progress"] = int(i / len(df) * 100)

        candle = df.iloc[i]
        ts     = candle['time']

        # Filtro sessione (London / NY)
        if not _in_session(ts):
            i += 1
            continue

        # Finestra di contesto
        ctx = df.iloc[max(0, i - CONTEXT): i + 1].copy().reset_index(drop=True)
        if len(ctx) < 60:
            i += 1
            continue

        # Segnale SMC
        try:
            signal = detector.analyze(ctx)
        except Exception:
            i += 1
            continue

        if signal is None:
            i += 1
            continue

        # Conferma ML
        if ml_model is not None:
            try:
                ctx_struct = detect_structure(ctx.copy())
                feat_df    = build_features(ctx_struct)
                if len(feat_df) == 0:
                    i += 1
                    continue
                conf = ml_model.predict_proba(feat_df)
                if conf < config.ML_CONFIDENCE_THRESHOLD:
                    i += 1
                    continue
            except Exception:
                pass  # se ML fallisce, usa solo segnale SMC

        # Parametri del trade
        entry   = float(candle['close'])
        sl      = float(signal.sl_price)
        tp      = float(signal.tp_price)
        dirn    = signal.direction   # "long" | "short"
        sl_dist = abs(entry - sl)
        tp_dist = abs(tp - entry)

        if sl_dist <= 0 or tp_dist <= 0:
            i += 1
            continue
        if tp_dist / sl_dist < 1.5:   # R:R minimo 1.5
            i += 1
            continue

        # Simula esito camminando sulle candele successive
        outcome    = None
        exit_price = None
        exit_time  = None
        exit_bar   = i

        for j in range(i + 1, min(i + MAX_HOLD + 1, len(df))):
            fut = df.iloc[j]
            if dirn == 'long':
                if fut['low'] <= sl:
                    outcome, exit_price, exit_time, exit_bar = 'SL', sl, fut['time'], j
                    break
                if fut['high'] >= tp:
                    outcome, exit_price, exit_time, exit_bar = 'TP', tp, fut['time'], j
                    break
            else:
                if fut['high'] >= sl:
                    outcome, exit_price, exit_time, exit_bar = 'SL', sl, fut['time'], j
                    break
                if fut['low'] <= tp:
                    outcome, exit_price, exit_time, exit_bar = 'TP', tp, fut['time'], j
                    break

        # Posizione ancora aperta a MAX_HOLD → chiudi al close
        if outcome is None:
            exit_bar   = min(i + MAX_HOLD, len(df) - 1)
            exit_price = float(df.iloc[exit_bar]['close'])
            exit_time  = df.iloc[exit_bar]['time']
            outcome    = 'WIN' if (
                (dirn == 'long'  and exit_price > entry) or
                (dirn == 'short' and exit_price < entry)
            ) else 'LOSS'

        # R multiplo del trade
        if dirn == 'long':
            raw_r = (exit_price - entry) / sl_dist
        else:
            raw_r = (entry - exit_price) / sl_dist

        # P&L in dollari (rischio fisso = RISK_PER_TRADE % del balance corrente)
        risk_amt = balance * config.RISK_PER_TRADE
        pnl      = raw_r * risk_amt
        balance += pnl

        # Drawdown
        if balance > max_equity:
            max_equity = balance
        dd = (max_equity - balance) / max_equity * 100
        if dd > max_dd_pct:
            max_dd_pct = dd

        is_win = outcome in ('TP', 'WIN')
        trades.append({
            "time":      str(ts)[:16],
            "exit_time": str(exit_time)[:16],
            "symbol":    symbol,
            "direction": dirn,
            "entry":     round(entry, 5),
            "sl":        round(sl, 5),
            "tp":        round(tp, 5),
            "exit":      round(float(exit_price), 5),
            "outcome":   "WIN" if is_win else "LOSS",
            "r":         round(raw_r, 2),
            "pnl":       round(pnl, 2),
        })

        if len(trades) % 20 == 0:
            _log(f"Trade simulati: {len(trades):3d} | Balance: ${balance:,.2f}")

        # Salta alla candela dopo la chiusura del trade
        i = exit_bar + 1

    # ── METRICHE ──────────────────────────────────────────────────────────────

    n = len(trades)
    if n == 0:
        raise ValueError(
            "Nessun trade generato nel periodo. "
            "Verifica che ci siano dati nelle kill zone (08-11 / 14-17) "
            "e che i segnali SMC si attivino. Prova un intervallo più lungo."
        )

    wins   = [t for t in trades if t['outcome'] == 'WIN']
    losses = [t for t in trades if t['outcome'] == 'LOSS']

    gross_profit = sum(t['pnl'] for t in wins)
    gross_loss   = abs(sum(t['pnl'] for t in losses)) or 1e-9
    r_series     = [t['r'] for t in trades]
    mean_r       = float(np.mean(r_series))
    std_r        = float(np.std(r_series))
    sharpe       = round(mean_r / std_r * np.sqrt(252), 2) if std_r > 0 and n > 1 else 0.0

    net_pnl     = balance - initial_balance
    net_pnl_pct = net_pnl / initial_balance * 100

    _log(f"{'─' * 50}")
    _log(f"  RISULTATI FINALI")
    _log(f"{'─' * 50}")
    _log(f"  Trade totali  : {n}")
    _log(f"  Win Rate      : {len(wins)/n*100:.1f}%  ({len(wins)}W / {len(losses)}L)")
    _log(f"  Profit Factor : {gross_profit/gross_loss:.2f}")
    _log(f"  Net R         : {sum(r_series):+.2f}R")
    _log(f"  Max Drawdown  : {max_dd_pct:.2f}%")
    _log(f"  Sharpe        : {sharpe:.2f}")
    _log(f"  Net P&L       : ${net_pnl:+,.2f}  ({net_pnl_pct:+.2f}%)")
    _log(f"  Balance fin.  : ${balance:,.2f}")
    _log(f"{'─' * 50}")

    return {
        "symbol":          symbol,
        "start_date":      start_date,
        "end_date":        end_date,
        "initial_balance": initial_balance,
        "final_balance":   round(balance, 2),
        "n_trades":        n,
        "n_wins":          len(wins),
        "n_losses":        len(losses),
        "win_rate":        round(len(wins) / n * 100, 1),
        "profit_factor":   round(gross_profit / gross_loss, 2),
        "net_r":           round(sum(r_series), 2),
        "avg_win_r":       round(float(np.mean([t['r'] for t in wins])),   2) if wins   else 0.0,
        "avg_loss_r":      round(float(np.mean([t['r'] for t in losses])), 2) if losses else 0.0,
        "max_dd_pct":      round(max_dd_pct, 2),
        "sharpe":          sharpe,
        "net_pnl":         round(net_pnl, 2),
        "net_pnl_pct":     round(net_pnl_pct, 2),
        "ml_used":         ml_model is not None,
        "trades":          trades[-200:],   # ultimi 200 per la tabella dashboard
    }


# ── PUBLIC API ────────────────────────────────────────────────────────────────

def start_backtest(symbol: str, start_date: str, end_date: str) -> bool:
    """Avvia il backtest in un thread separato. Ritorna False se già in corso."""
    with _lock:
        if _state["running"]:
            return False
        _state.update(
            running=True, progress=0, status="running",
            results=None, error=None, log=[]
        )

    def _run():
        try:
            results = run_backtest(symbol, start_date, end_date)
            with _lock:
                _state["results"]  = results
                _state["status"]   = "done"
                _state["progress"] = 100
        except Exception as e:
            _log(f"ERRORE BACKTEST: {e}")
            with _lock:
                _state["error"]  = str(e)
                _state["status"] = "error"
        finally:
            with _lock:
                _state["running"] = False

    threading.Thread(target=_run, daemon=True).start()
    return True


def get_status() -> Dict[str, Any]:
    with _lock:
        return copy.deepcopy(_state)
