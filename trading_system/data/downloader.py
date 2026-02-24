"""
Downloader Dati Storici da MT5
================================
Scarica automaticamente i dati OHLCV storici da MetaTrader 5
e li salva nella cartella data/ pronti per il training del modello.

Uso da riga di comando:
    python trading_system/data/downloader.py

Uso da codice:
    from trading_system.data.downloader import start_download, get_status
    start_download(years=4)
    status = get_status()
"""

import os
import sys
import threading
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

from trading_system import config

logger = logging.getLogger(__name__)

try:
    import MetaTrader5 as mt5
    MT5_AVAILABLE = True
except ImportError:
    MT5_AVAILABLE = False
    mt5 = None

# ─── STATO CONDIVISO (thread-safe via lock) ───────────────────────────────────

_lock = threading.Lock()

_status = {
    "running":   False,
    "done":      False,
    "error":     None,
    "symbols":   {},   # { "XAUUSD": { "state": "pending|downloading|done|error", "rows": 0, "from": "", "to": "", "msg": "" } }
    "started_at": None,
    "ended_at":  None,
}


def get_status() -> dict:
    """Ritorna una copia dello stato corrente del download."""
    with _lock:
        import copy
        return copy.deepcopy(_status)


def _set(key, value):
    with _lock:
        _status[key] = value


def _set_symbol(symbol, **kwargs):
    with _lock:
        if symbol not in _status["symbols"]:
            _status["symbols"][symbol] = {"state": "pending", "rows": 0, "from": "", "to": "", "msg": ""}
        _status["symbols"][symbol].update(kwargs)


# ─── DOWNLOAD ─────────────────────────────────────────────────────────────────

def _download_symbol(symbol: str, years: int):
    """Scarica i dati M5 per un simbolo e li salva come CSV."""
    _set_symbol(symbol, state="downloading", msg="Connessione a MT5...")

    if not MT5_AVAILABLE:
        _set_symbol(symbol, state="error",
                    msg="MetaTrader5 non installato. Installa con: pip install MetaTrader5 (solo Windows)")
        return

    date_to   = datetime.now(timezone.utc)
    date_from = date_to - timedelta(days=365 * years)

    # Seleziona il simbolo
    if not mt5.symbol_select(symbol, True):
        _set_symbol(symbol, state="error", msg=f"Simbolo '{symbol}' non disponibile su MT5")
        return

    _set_symbol(symbol, msg=f"Download {symbol} da {date_from.strftime('%Y-%m-%d')} a {date_to.strftime('%Y-%m-%d')}...")

    rates = mt5.copy_rates_range(symbol, mt5.TIMEFRAME_M5, date_from, date_to)

    if rates is None or len(rates) == 0:
        err = mt5.last_error()
        _set_symbol(symbol, state="error", msg=f"Nessun dato ricevuto da MT5: {err}")
        return

    # Costruisci DataFrame
    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s")
    df = df.rename(columns={"time": "datetime", "tick_volume": "volume"})
    df = df[["datetime", "open", "high", "low", "close", "volume"]]
    df = df.set_index("datetime").sort_index()

    rows = len(df)
    date_start = df.index[0].strftime("%Y-%m-%d")
    date_end   = df.index[-1].strftime("%Y-%m-%d")

    # Salva CSV
    out_dir  = ROOT / config.DATA_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{symbol}_M5.csv"

    df.to_csv(out_path)

    _set_symbol(symbol,
                state="done",
                rows=rows,
                **{"from": date_start, "to": date_end},
                msg=f"Salvato: {rows:,} candele  ({date_start} → {date_end})")

    logger.info(f"[Downloader] {symbol}: {rows:,} candele salvate in {out_path}")


def _run_download(years: int):
    """Thread principale del download."""
    _set("running", True)
    _set("done", False)
    _set("error", None)
    _set("started_at", datetime.now().isoformat())
    _set("ended_at", None)

    with _lock:
        _status["symbols"] = {}

    if not MT5_AVAILABLE:
        _set("running", False)
        _set("done", True)
        _set("error", "MetaTrader5 non installato. Esegui: pip install MetaTrader5  (richiede Windows + MT5)")
        return

    # Inizializza MT5 (login deve essere int)
    try:
        mt5_login = int(config.MT5_ACCOUNT) if config.MT5_ACCOUNT else None
    except (ValueError, TypeError):
        mt5_login = None

    ok = mt5.initialize(
        login=mt5_login,
        password=config.MT5_PASSWORD if config.MT5_PASSWORD else None,
        server=config.MT5_SERVER if config.MT5_SERVER else None,
    )

    if not ok:
        err = mt5.last_error()
        _set("running", False)
        _set("done", True)
        _set("error", f"MT5 non avviato o non connesso: {err}. Apri MetaTrader5 prima di scaricare.")
        return

    try:
        for symbol in config.SYMBOLS:
            _download_symbol(symbol, years)
    finally:
        mt5.shutdown()
        _set("running", False)
        _set("done", True)
        _set("ended_at", datetime.now().isoformat())


def start_download(years: int = 4) -> bool:
    """
    Avvia il download in background.
    Ritorna True se avviato, False se già in corso.
    """
    with _lock:
        if _status["running"]:
            return False

    thread = threading.Thread(target=_run_download, args=(years,), daemon=True)
    thread.start()
    return True


# ─── CLI ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

    years = 4
    if len(sys.argv) > 1:
        try:
            years = int(sys.argv[1])
        except ValueError:
            pass

    print(f"\nDownload dati storici MT5 — ultimi {years} anni")
    print(f"Simboli: {config.SYMBOLS}")
    print(f"Cartella output: {ROOT / config.DATA_DIR}\n")

    if not MT5_AVAILABLE:
        print("[ERRORE] MetaTrader5 non installato.")
        print("  pip install MetaTrader5   (solo Windows con MT5 installato)")
        sys.exit(1)

    import time
    start_download(years=years)

    while True:
        s = get_status()
        for sym, info in s["symbols"].items():
            print(f"  {sym}: [{info['state'].upper()}] {info['msg']}")
        if s["done"]:
            if s["error"]:
                print(f"\n[ERRORE] {s['error']}")
                sys.exit(1)
            print("\nDownload completato!")
            print("Ora puoi addestrare il modello con: python trading_system/ml/train.py")
            break
        time.sleep(2)
        print("---")
