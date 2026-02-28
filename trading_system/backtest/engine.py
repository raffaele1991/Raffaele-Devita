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

def _in_session(ts: pd.Timestamp, symbol: str = "") -> bool:
    """
    Verifica se la candela cade in una kill zone.
    I dati MT5 sono in ora broker (solitamente UTC+2/+3, simile a CET/CEST).
    Usiamo direttamente l'ora del timestamp senza conversione timezone.
    London: 08:00–11:00 | NY: 14:00–17:00 | Asian: 00:00–04:00 (solo ASIAN_SESSION_SYMBOLS)
    """
    try:
        h = ts.hour
        in_london = 8 <= h < 11
        in_ny     = 14 <= h < 17
        asian_symbols = [s.upper() for s in getattr(config, 'ASIAN_SESSION_SYMBOLS', [])]
        in_asian  = (0 <= h < 4) and (symbol.upper() in asian_symbols)
        return in_london or in_ny or in_asian
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

def _htf_trend(ctx: pd.DataFrame) -> int:
    """
    Approssima il trend M30 usando EMA120/EMA300 su M5 (equivalenti EMA20/EMA50 su M30).
    Questo evita il problema del resample che genera troppo pochi bar M30 dalla finestra
    di contesto M5 (200 bar M5 → ~33 bar M30, insufficienti per EMA50).

    EMA120 su M5 ≈ EMA20 su M30 (120 = 20 × 6)
    EMA300 su M5 ≈ EMA50 su M30 (300 = 50 × 6, cappato a lunghezza contesto)

    Ritorna 1 (bull), -1 (bear), 0 (neutro / dati insufficienti).
    """
    try:
        close = ctx['close'] if 'close' in ctx.columns else None
        if close is None or len(close) < 30:
            return 0
        ema_fast = close.ewm(span=min(120, len(close) - 1), adjust=False).mean().iloc[-1]
        ema_slow = close.ewm(span=min(300, len(close) - 1), adjust=False).mean().iloc[-1]
        if ema_fast > ema_slow:
            return 1
        elif ema_fast < ema_slow:
            return -1
        return 0
    except Exception:
        return 0


def run_backtest(
    symbol: str,
    start_date: str,
    end_date: str,
    initial_balance: float = 10_000.0,
    ml_threshold: Optional[float] = None,
    htf_hard_filter: Optional[bool] = None,
    require_fvg: Optional[bool] = None,
    require_liq_sweep: Optional[bool] = None,
) -> Dict[str, Any]:

    # Parametri: None = usa config per-simbolo (se disponibile) o default globale
    _by_sym   = getattr(config, 'ML_CONFIDENCE_BY_SYMBOL', {}).get(symbol.upper(), None)
    threshold = ml_threshold if ml_threshold is not None else (_by_sym if _by_sym is not None else config.ML_CONFIDENCE_THRESHOLD)

    # Leggi config per-simbolo (es. EURUSD usa Liq Sweep, XAUUSD usa FVG)
    _sym_cfg = getattr(config, 'SYMBOL_FILTER_CONFIGS', {}).get(symbol.upper(), {})
    if htf_hard_filter is None:
        htf_hard_filter   = _sym_cfg.get('htf_align',        getattr(config, 'SMC_REQUIRE_HTF_ALIGN',  False))
    if require_fvg is None:
        require_fvg       = _sym_cfg.get('require_fvg',      getattr(config, 'SMC_REQUIRE_FVG',        False))
    if require_liq_sweep is None:
        require_liq_sweep = _sym_cfg.get('require_liq_sweep', getattr(config, 'SMC_REQUIRE_LIQ_SWEEP', False))

    _log(f"{'=' * 50}")
    _log(f"  BACKTEST {symbol}")
    _log(f"  Periodo: {start_date} → {end_date}")
    _log(f"  ML threshold  : {threshold}")
    _log(f"  HTF hard filter : {htf_hard_filter}")
    _log(f"  Require FVG     : {require_fvg}")
    _log(f"  Require Liq Sweep: {require_liq_sweep}")
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

    # 2. Carica modello ML (opzionale, controllato da config.USE_ML_FILTER)
    ml_model: Optional[SMCMLModel] = None
    if not config.USE_ML_FILTER:
        _log("Filtro ML disabilitato (USE_ML_FILTER=False) → backtest solo SMC")
    else:
        model_path = os.path.join(
            os.path.dirname(__file__), '..', 'models',
            f"model_{symbol.lower()}.pkl"
        )
        if os.path.exists(model_path):
            try:
                ml_model = SMCMLModel(symbol)
                ml_model.load()
                _log(f"Modello ML caricato ✓  (soglia={config.ML_CONFIDENCE_THRESHOLD})")
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

    # Contatori diagnostici
    _diag = {
        "session_bars":    0,
        "no_trend":        0,
        "no_ob":           0,
        "htf_blocked":     0,
        "fvg_blocked":     0,
        "liq_blocked":     0,
        "ml_blocked":      0,
        "rr_rejected":     0,
        "signals":         0,
        "signals_with_fvg": 0,
        "signals_with_liq": 0,
    }

    _log(f"Avvio simulazione...")

    while i < len(df):
        # Aggiorna progresso globale
        with _lock:
            _state["progress"] = int(i / len(df) * 100)

        candle = df.iloc[i]
        ts     = candle['time']

        # Filtro sessione (London / NY / Asian per USDJPY)
        if not _in_session(ts, symbol):
            i += 1
            continue

        _diag["session_bars"] += 1

        # Finestra di contesto
        ctx = df.iloc[max(0, i - CONTEXT): i + 1].copy().reset_index(drop=True)
        if len(ctx) < 60:
            i += 1
            continue

        # Segnale SMC (return_struct=True per riusare la struttura già calcolata per ML)
        try:
            signal, ctx_struct = detector.analyze(ctx, return_struct=True)
        except Exception as e:
            _log(f"  [DIAG] Eccezione detector: {e}")
            i += 1
            continue

        if signal is None:
            # Capisce il motivo: trend o OB
            if ctx_struct is not None:
                trend_val = ctx_struct.iloc[-1].get("trend", 0) if hasattr(ctx_struct.iloc[-1], "get") else ctx_struct["trend"].iloc[-1]
                if trend_val == 0:
                    _diag["no_trend"] += 1
                else:
                    _diag["no_ob"] += 1
            i += 1
            continue

        _diag["signals"] += 1

        # Traccia confluenze (per diagnostica)
        has_fvg = signal.fvg_top > 0
        has_liq = signal.liquidity_swept
        if has_fvg:
            _diag["signals_with_fvg"] += 1
        if has_liq:
            _diag["signals_with_liq"] += 1

        # Hard filter HTF: scarta segnali contro il trend M30
        if htf_hard_filter:
            ht = _htf_trend(ctx)
            if ht != 0:
                sig_dir = 1 if signal.direction == 'long' else -1
                if sig_dir != ht:
                    _diag["htf_blocked"] += 1
                    i += 1
                    continue

        # Hard filter FVG: entra solo se c'è un FVG confluente nella zona OB
        if require_fvg and not has_fvg:
            _diag["fvg_blocked"] += 1
            i += 1
            continue

        # Hard filter Liquidity Sweep: entra solo se c'è stato sweep prima del rimbalzo
        if require_liq_sweep and not has_liq:
            _diag["liq_blocked"] += 1
            i += 1
            continue

        # Conferma ML (riusa ctx_struct già calcolato sopra — nessuna doppia elaborazione)
        if ml_model is not None:
            try:
                # build_features richiede un DatetimeIndex (usa df.index.hour per le sessioni)
                ctx_for_ml = ctx_struct.copy()
                if 'time' in ctx_for_ml.columns:
                    ctx_for_ml = ctx_for_ml.set_index('time')
                feat_df = build_features(ctx_for_ml, symbol=symbol)
                if len(feat_df) == 0:
                    _diag["ml_blocked"] += 1
                    i += 1
                    continue
                conf = ml_model.predict_proba(feat_df)
                _log(f"  [ML] conf={conf:.3f} soglia={threshold} dir={signal.direction}")
                if conf < threshold:
                    _diag["ml_blocked"] += 1
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
            if _diag["rr_rejected"] < 3:
                _log(f"  [RR-DEBUG] sl_dist={sl_dist:.6f} tp_dist={tp_dist:.6f} entry={entry:.5f} sl={sl:.5f} tp={tp:.5f} dir={dirn}")
            _diag["rr_rejected"] += 1
            i += 1
            continue
        rr = tp_dist / sl_dist
        if rr < 1.5:   # R:R minimo 1.5
            if _diag["rr_rejected"] < 3:
                _log(f"  [RR-DEBUG] RR={rr:.3f}<1.5 entry={entry:.5f} sl={sl:.5f} tp={tp:.5f} dir={dirn}")
            _diag["rr_rejected"] += 1
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
                sl_hit = fut['low']  <= sl
                tp_hit = fut['high'] >= tp
                if sl_hit and tp_hit:
                    # Entrambi nella stessa candela M5: usa la direzione della candela
                    # come proxy dell'ordine intra-bar (bullish → TP colpito prima)
                    if fut['close'] >= fut['open']:
                        outcome, exit_price, exit_time, exit_bar = 'TP', tp, fut['time'], j
                    else:
                        outcome, exit_price, exit_time, exit_bar = 'SL', sl, fut['time'], j
                    break
                elif sl_hit:
                    outcome, exit_price, exit_time, exit_bar = 'SL', sl, fut['time'], j
                    break
                elif tp_hit:
                    outcome, exit_price, exit_time, exit_bar = 'TP', tp, fut['time'], j
                    break
            else:
                sl_hit = fut['high'] >= sl
                tp_hit = fut['low']  <= tp
                if sl_hit and tp_hit:
                    # Candela bearish → TP colpito prima nel setup short
                    if fut['close'] <= fut['open']:
                        outcome, exit_price, exit_time, exit_bar = 'TP', tp, fut['time'], j
                    else:
                        outcome, exit_price, exit_time, exit_bar = 'SL', sl, fut['time'], j
                    break
                elif sl_hit:
                    outcome, exit_price, exit_time, exit_bar = 'SL', sl, fut['time'], j
                    break
                elif tp_hit:
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

        # P&L in dollari (rischio fisso = RISK_PER_TRADE_PCT % del balance corrente)
        risk_amt = balance * config.RISK_PER_TRADE_PCT
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

    # ── DIAGNOSTICA ───────────────────────────────────────────────────────────

    _log(f"{'─' * 50}")
    _log(f"  DIAGNOSTICA FILTRI")
    _log(f"  Candele in sessione  : {_diag['session_bars']}")
    _log(f"  Scartate (no trend)  : {_diag['no_trend']}")
    _log(f"  Scartate (no OB hit) : {_diag['no_ob']}")
    _log(f"  Segnali SMC trovati  : {_diag['signals']}")
    _log(f"  di cui con FVG       : {_diag['signals_with_fvg']}  ({_diag['signals_with_fvg']/max(_diag['signals'],1)*100:.0f}%)")
    _log(f"  di cui con Liq Sweep : {_diag['signals_with_liq']}  ({_diag['signals_with_liq']/max(_diag['signals'],1)*100:.0f}%)")
    _log(f"  Bloccati da HTF      : {_diag['htf_blocked']}")
    _log(f"  Bloccati (no FVG)    : {_diag['fvg_blocked']}")
    _log(f"  Bloccati (no Liq)    : {_diag['liq_blocked']}")
    _log(f"  Bloccati da ML       : {_diag['ml_blocked']}")
    _log(f"  Rifiutati (R:R basso): {_diag['rr_rejected']}")
    _log(f"  Trade aperti         : {len(trades)}")
    _log(f"{'─' * 50}")

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
    avg_win_r  = float(np.mean([t['r'] for t in wins]))   if wins   else 0.0
    avg_loss_r = float(np.mean([t['r'] for t in losses])) if losses else 0.0

    _log(f"  Trade totali  : {n}")
    _log(f"  Win Rate      : {len(wins)/n*100:.1f}%  ({len(wins)}W / {len(losses)}L)")
    _log(f"  Avg Win R     : {avg_win_r:+.2f}R")
    _log(f"  Avg Loss R    : {avg_loss_r:+.2f}R")
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

def start_backtest(symbol: str, start_date: str, end_date: str, ml_threshold: Optional[float] = None) -> bool:
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
            results = run_backtest(symbol, start_date, end_date, ml_threshold=ml_threshold)
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
