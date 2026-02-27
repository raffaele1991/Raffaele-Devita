"""
Dukascopy Historical Data Downloader — TURBO con Resume
=========================================================
Output:
    trading_system/data/{SYMBOL}_dukascopy.csv
    trading_system/data/{SYMBOL}_dukascopy_progress.txt  ← resume automatico

Resume: se interrompi (Ctrl+C o crash), rilancia lo stesso comando.
        Riparte dall'ultimo giorno completato per ogni simbolo.

Uso:
    python trading_system/data/dukascopy_downloader.py

Ottimizzazioni:
  • Tutti i simboli scaricati in parallelo nello stesso pool (non uno per volta)
  • Aggregazione tick→M5 inline nel worker — zero pandas in volo, ~100x meno RAM
  • WORKERS=60, HTTPAdapter pool_maxsize=80 (connessioni realmente parallele)
  • TIMEOUT=12 s — fail veloce sulle ore vuote che tardano a rispondere
  • struct.Struct cached + iter_unpack (no slicing per tick)
  • Bar bucket calcolato con aritmetica intera su epoch ms (no datetime.replace)
  • Scrittura CSV incrementale giorno per giorno (resume sicuro)
"""

import csv
import lzma
import logging
import os
import struct
import sys
import time
from concurrent.futures import ThreadPoolExecutor, wait as fut_wait
from datetime import datetime, timedelta, timezone

import pandas as pd
import requests
from requests.adapters import HTTPAdapter

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
from trading_system import config

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger(__name__)

# ─── CONFIGURAZIONE ────────────────────────────────────────────────────────────

PRICE_DIVISOR = {
    "XAUUSD": 1000,
    "EURUSD": 100000,
    "GBPUSD": 100000,
    "USDJPY": 1000,
}

SYMBOL_START = {
    "EURUSD": datetime(2003, 5, 1, tzinfo=timezone.utc),
    "GBPUSD": datetime(2003, 5, 1, tzinfo=timezone.utc),
    "USDJPY": datetime(2003, 5, 1, tzinfo=timezone.utc),
    "XAUUSD": datetime(2003, 8, 1, tzinfo=timezone.utc),
}

DATA_DIR = os.path.join(ROOT, config.DATA_DIR)
DATE_END = datetime.now(tz=timezone.utc).replace(hour=23, minute=59, second=59)

WORKERS = 60   # thread paralleli — tutti i simboli insieme
RETRY   = 2    # tentativi per ora fallita
TIMEOUT = 12   # secondi — fail veloce sulle ore vuote

# ─── HTTP SESSION ──────────────────────────────────────────────────────────────

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "Mozilla/5.0"})
_adapter = HTTPAdapter(pool_connections=80, pool_maxsize=80, max_retries=0)
SESSION.mount("https://", _adapter)

_TICK    = struct.Struct(">IIIff")
_5MIN_MS = 300_000   # 5 minuti in millisecondi


# ─── WORKER: download + aggregazione M5 inline ─────────────────────────────────

def download_hour(symbol: str, dt: datetime) -> dict:
    """
    Scarica 1 ora di tick e aggrega inline in barre M5.
    Ritorna {bar_epoch_ms: [O, H, L, C, tick_count]} — vuoto se nessun dato.
    Non crea mai un DataFrame: usa solo dict e aritmetica intera.
    """
    url = (
        f"https://datafeed.dukascopy.com/datafeed/{symbol}/"
        f"{dt.year}/{dt.month - 1:02d}/{dt.day:02d}/{dt.hour:02d}h_ticks.bi5"
    )
    divisor = PRICE_DIVISOR.get(symbol, 100000)

    for attempt in range(RETRY):
        try:
            r = SESSION.get(url, timeout=TIMEOUT)
            if r.status_code == 404 or not r.content:
                return {}
            if r.status_code != 200:
                time.sleep(1)
                continue

            raw = lzma.decompress(r.content)
            if not raw:
                return {}

            hour_epoch_ms = int(dt.timestamp() * 1000)
            bars: dict = {}
            for ms_raw, ask_i, bid_i, _, _ in _TICK.iter_unpack(raw):
                mid = (ask_i + bid_i) / 2 / divisor
                bar_key = (hour_epoch_ms + int(ms_raw)) // _5MIN_MS * _5MIN_MS
                b = bars.get(bar_key)
                if b is None:
                    bars[bar_key] = [mid, mid, mid, mid, 1]
                else:
                    if mid > b[1]: b[1] = mid  # H
                    if mid < b[2]: b[2] = mid  # L
                    b[3] = mid                 # C
                    b[4] += 1                  # volume
            return bars

        except lzma.LZMAError:
            return {}
        except Exception:
            if attempt < RETRY - 1:
                time.sleep(2 ** attempt)

    return {}


# ─── MERGE BARRE ───────────────────────────────────────────────────────────────

def _merge_into(target: dict, source: dict) -> None:
    for key, (o, h, l, c, v) in source.items():
        b = target.get(key)
        if b is None:
            target[key] = [o, h, l, c, v]
        else:
            if h > b[1]: b[1] = h
            if l < b[2]: b[2] = l
            b[3] = c
            b[4] += v


# ─── PROGRESS FILE (resume) ────────────────────────────────────────────────────

def _progress_path(symbol: str) -> str:
    return os.path.join(DATA_DIR, f"{symbol}_dukascopy_progress.txt")

def load_progress(symbol: str) -> datetime | None:
    p = _progress_path(symbol)
    if not os.path.exists(p):
        return None
    try:
        line = open(p).read().strip()
        return datetime.strptime(line, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except Exception:
        return None

def save_progress(symbol: str, day: datetime) -> None:
    with open(_progress_path(symbol), "w") as f:
        f.write(day.strftime("%Y-%m-%d"))


# ─── SCRITTURA CSV INCREMENTALE ────────────────────────────────────────────────

def _csv_path(symbol: str) -> str:
    return os.path.join(DATA_DIR, f"{symbol}_dukascopy.csv")

def _write_bars(symbol: str, bars: dict, write_header: bool) -> None:
    """Scrive (o appende) le barre del giorno corrente al CSV."""
    path = _csv_path(symbol)
    mode = "w" if write_header else "a"
    with open(path, mode, newline="") as f:
        w = csv.writer(f)
        if write_header:
            w.writerow(["datetime", "open", "high", "low", "close", "volume"])
        for key in sorted(bars.keys()):
            o, h, l, c, v = bars[key]
            dt = datetime.utcfromtimestamp(key / 1000).replace(tzinfo=timezone.utc)
            fmt = ".5f" if o < 100 else ".3f"
            w.writerow([
                dt.strftime("%Y-%m-%d %H:%M:%S"),
                format(o, fmt), format(h, fmt), format(l, fmt), format(c, fmt),
                f"{v:.0f}",
            ])


# ─── MERGE CON DATI MT5 ESISTENTI ─────────────────────────────────────────────

def merge_with_mt5(symbol: str) -> None:
    duka_path = _csv_path(symbol)
    mt5_path  = os.path.join(DATA_DIR, f"{symbol}_M5.csv")

    if not os.path.exists(duka_path):
        logger.error(f"File Dukascopy non trovato: {duka_path}")
        return

    dfs = []
    df_duka = pd.read_csv(duka_path, index_col="datetime", parse_dates=True)
    df_duka.columns = [c.lower() for c in df_duka.columns]
    dfs.append(df_duka)

    if os.path.exists(mt5_path):
        df_mt5 = pd.read_csv(mt5_path, index_col="datetime", parse_dates=True)
        df_mt5.columns = [c.lower() for c in df_mt5.columns]
        dfs.append(df_mt5[["open", "high", "low", "close", "volume"]])
    else:
        logger.warning(f"File MT5 non trovato: {mt5_path} — uso solo Dukascopy")

    combined = pd.concat(dfs).sort_index()
    combined = combined[~combined.index.duplicated(keep="last")]
    combined[["open", "high", "low", "close", "volume"]].to_csv(
        mt5_path, index_label="datetime"
    )
    logger.info(f"  MERGE {symbol}: {len(combined):,} candele → {mt5_path}")


# ─── MAIN ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    t0 = time.time()
    symbols = list(config.SYMBOLS)

    os.makedirs(DATA_DIR, exist_ok=True)

    # ── Calcola giorni rimanenti per simbolo (rispettando il resume) ─────────────
    sym_remaining: dict[str, set] = {}
    sym_write_header: dict[str, bool] = {}

    for sym in symbols:
        last_done = load_progress(sym)
        if last_done:
            start = (last_done + timedelta(days=1)).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            sym_write_header[sym] = False   # appende al CSV esistente
            print(f"  {sym}: RESUME da {start.date()}")
        else:
            start = SYMBOL_START.get(sym, datetime(2003, 5, 1, tzinfo=timezone.utc))
            start = start.replace(hour=0, minute=0, second=0, microsecond=0)
            sym_write_header[sym] = True    # nuovo CSV con header
            print(f"  {sym}: start da {start.date()}")

        days: set = set()
        d = start
        while d <= DATE_END:
            if d.weekday() != 6:   # salta domeniche
                days.add(d)
            d += timedelta(days=1)
        sym_remaining[sym] = days

    # ── Lista giorni unici (unione di tutti i simboli) ───────────────────────────
    all_days = sorted(set(d for days in sym_remaining.values() for d in days))
    total_days = len(all_days)
    total_hours = sum(len(days) * 24 for days in sym_remaining.values())

    sym_abbrev = {sym: sym[:2] for sym in symbols}  # "EURUSD" → "EU"

    print(f"\n{'='*65}")
    print(f"  TURBO Dukascopy — {len(symbols)} simboli in parallelo con resume")
    print(f"  Giorni unici: {total_days:,}  |  Ore totali: {total_hours:,}")
    print(f"  Worker: {WORKERS}  |  Timeout: {TIMEOUT}s")
    print(f"  Output: {DATA_DIR}/")
    print(f"  Stima: ~{total_hours / WORKERS * 0.4 / 60:.0f} min")
    print(f"{'='*65}\n")
    print(f"  {'Data':<12} {'[Progress     ]':15} {'%':>6}  Barre/simbolo{' ':>10} ETA")
    print(f"  {'-'*70}")

    # Contatori globali
    sym_total_bars: dict[str, int] = {sym: 0 for sym in symbols}

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:

        for day_idx, day in enumerate(all_days, 1):

            # Simboli attivi per questo giorno
            active = [sym for sym in symbols if day in sym_remaining[sym]]
            if not active:
                continue

            # Sottometti tutte le 24 ore × simboli attivi
            day_futures: dict = {}
            for sym in active:
                for h in range(24):
                    fut = pool.submit(download_hour, sym, day.replace(hour=h))
                    day_futures[fut] = sym

            # Attendi il completamento di tutte le ore del giorno
            done_futs, _ = fut_wait(day_futures.keys())

            # Raccogli barre per simbolo
            day_bars: dict[str, dict] = {sym: {} for sym in active}
            for fut in done_futs:
                sym  = day_futures[fut]
                data = fut.result()
                if data:
                    _merge_into(day_bars[sym], data)

            # Scrivi CSV + salva progress per ogni simbolo attivo
            for sym in active:
                if day_bars[sym]:
                    _write_bars(sym, day_bars[sym], sym_write_header[sym])
                    sym_write_header[sym] = False
                    sym_total_bars[sym] += len(day_bars[sym])
                save_progress(sym, day)

            # ── Progress line ──────────────────────────────────────────────────
            pct     = day_idx / total_days * 100
            elapsed = time.time() - t0
            eta_min = (total_days - day_idx) / max(day_idx, 1) * elapsed / 60
            vis_len = 14
            filled  = int(pct / 100 * vis_len)
            bar_vis = "#" * filled + "." * (vis_len - filled)
            bars_str = "  ".join(
                f"{sym_abbrev[sym]}:{sym_total_bars[sym]:>7,}" for sym in symbols
            )
            print(
                f"  {day.strftime('%Y-%m-%d')}  [{bar_vis}] {pct:5.1f}%"
                f"  {bars_str}  ETA≈{eta_min:.0f}min"
            )

    # ── Merge finale con dati MT5 ────────────────────────────────────────────────
    print(f"\n{'='*65}")
    print("  Merge con dati MT5 esistenti...")
    for sym in symbols:
        if sym_total_bars[sym] > 0 or load_progress(sym):
            merge_with_mt5(sym)
        else:
            logger.error(f"  Nessun dato scaricato per {sym}")

    elapsed = (time.time() - t0) / 60
    print(f"\n  Completato in {elapsed:.1f} minuti")
    print(f"  File salvati in: {DATA_DIR}/")
    print("  Aggiorna TRAIN_CUTOFF_DATE in config.py, poi ri-esegui train.py")
