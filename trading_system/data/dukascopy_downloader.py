"""
Dukascopy Historical Data Downloader
======================================
Scarica dati tick da Dukascopy (gratuiti) per tutti i simboli configurati
e li aggrega in candele M5 salvate come CSV compatibili col sistema.

Copertura Dukascopy:
  EURUSD / GBPUSD / USDJPY → dal 2003-05
  XAUUSD                   → dal 2003-08

Uso:
    python trading_system/data/dukascopy_downloader.py
"""

import os
import sys
import lzma
import struct
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone

import pandas as pd
import requests

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
from trading_system import config

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger(__name__)

# ─── CONFIGURAZIONE ────────────────────────────────────────────────────────────

# Divisore prezzi per simbolo (Dukascopy scala i prezzi come interi)
# Forex a 5 decimali: divide per 100000 (es. EURUSD: 112345 → 1.12345)
# JPY e Gold a 3 decimali: divide per 1000 (es. USDJPY: 156789 → 156.789)
PRICE_DIVISOR = {
    "XAUUSD": 1000,     # oro: 1518600 / 1000 = 1518.600
    "EURUSD": 100000,   # forex 5 dec: 112000 / 100000 = 1.12000
    "GBPUSD": 100000,
    "USDJPY": 1000,     # JPY 3 dec: 156789 / 1000 = 156.789
}

# Data di inizio per-simbolo (Dukascopy non ha dati prima di queste date)
SYMBOL_START = {
    "EURUSD": datetime(2003,  5, 1, tzinfo=timezone.utc),
    "GBPUSD": datetime(2003,  5, 1, tzinfo=timezone.utc),
    "USDJPY": datetime(2003,  5, 1, tzinfo=timezone.utc),
    "XAUUSD": datetime(2003,  8, 1, tzinfo=timezone.utc),
}

# Fine periodo = oggi (dinamico)
DATE_END = datetime.now(tz=timezone.utc).replace(hour=23, minute=59, second=59)

WORKERS    = 30    # thread paralleli (aumentati per dataset grande)
RETRY      = 3     # tentativi per file
TIMEOUT    = 30    # secondi timeout HTTP

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "Mozilla/5.0"})


# ─── DOWNLOAD SINGOLA ORA ──────────────────────────────────────────────────────

def download_hour(symbol: str, dt: datetime) -> pd.DataFrame | None:
    """
    Scarica e decomprime 1 ora di tick data da Dukascopy.
    Ritorna DataFrame con colonne [timestamp, price] o None se vuoto/assente.
    """
    # Mesi 0-indexed in Dukascopy
    url = (
        f"https://datafeed.dukascopy.com/datafeed/{symbol}/"
        f"{dt.year}/{dt.month - 1:02d}/{dt.day:02d}/{dt.hour:02d}h_ticks.bi5"
    )

    for attempt in range(RETRY):
        try:
            r = SESSION.get(url, timeout=TIMEOUT)
            if r.status_code == 404 or len(r.content) == 0:
                return None  # ora vuota (notte/weekend)
            if r.status_code != 200:
                time.sleep(1)
                continue

            raw = lzma.decompress(r.content)
            n   = len(raw) // 20
            if n == 0:
                return None

            divisor = PRICE_DIVISOR.get(symbol, 100000)
            records = []
            for i in range(n):
                ms, ask, bid, _, _ = struct.unpack(">IIIff", raw[i * 20: i * 20 + 20])
                ts  = dt + timedelta(milliseconds=int(ms))
                mid = (ask + bid) / 2 / divisor
                records.append((ts, mid))

            return pd.DataFrame(records, columns=["timestamp", "price"])

        except Exception:
            time.sleep(2 ** attempt)

    return None


# ─── AGGREGAZIONE M5 ───────────────────────────────────────────────────────────

def ticks_to_m5(ticks: pd.DataFrame) -> pd.DataFrame:
    """Aggrega tick in candele M5 OHLCV."""
    ticks = ticks.set_index("timestamp").sort_index()
    ticks["volume"] = 1  # ogni tick = 1 unità di volume

    ohlcv = ticks["price"].resample("5min").ohlc()
    ohlcv["volume"] = ticks["volume"].resample("5min").sum()
    ohlcv = ohlcv.dropna()
    return ohlcv


# ─── DOWNLOAD COMPLETO PER SIMBOLO ────────────────────────────────────────────

def download_symbol(symbol: str):
    date_start = SYMBOL_START.get(symbol, datetime(2003, 5, 1, tzinfo=timezone.utc))

    logger.info(f"\n{'='*60}")
    logger.info(f"  Dukascopy download: {symbol}")
    logger.info(f"  Periodo: {date_start.date()} → {DATE_END.date()}")
    logger.info(f"{'='*60}")

    # Genera lista di tutte le ore nel periodo
    hours = []
    dt = date_start
    while dt <= DATE_END:
        # Salta domeniche (mercato chiuso)
        if dt.weekday() != 6:
            hours.append(dt)
        dt += timedelta(hours=1)

    total = len(hours)
    logger.info(f"  Ore da scaricare: {total:,}")

    # Download parallelo
    all_ticks = []
    done = 0

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = {pool.submit(download_hour, symbol, h): h for h in hours}
        for fut in as_completed(futures):
            result = fut.result()
            if result is not None and len(result) > 0:
                all_ticks.append(result)
            done += 1
            if done % 500 == 0:
                logger.info(f"  Progresso: {done:,}/{total:,} ore ({done/total*100:.1f}%)")

    if not all_ticks:
        logger.error(f"  Nessun dato ricevuto per {symbol}")
        return

    logger.info(f"  Aggregazione tick → M5...")
    ticks = pd.concat(all_ticks).sort_values("timestamp").drop_duplicates("timestamp")
    m5    = ticks_to_m5(ticks)

    logger.info(f"  Candele M5 generate: {len(m5):,}")
    logger.info(f"  Periodo: {m5.index[0]} → {m5.index[-1]}")

    # Salva CSV
    out_path = os.path.join(ROOT, config.DATA_DIR, f"{symbol}_dukascopy.csv")
    m5.index.name = "datetime"
    m5.to_csv(out_path)
    logger.info(f"  Salvato: {out_path}")

    return out_path


# ─── MERGE CON DATI MT5 ESISTENTI ─────────────────────────────────────────────

def merge_with_mt5(symbol: str):
    """
    Unisce dati Dukascopy (2020-2024) con dati MT5 (2024-2026)
    e salva un CSV combinato pronto per il training.
    """
    data_dir = os.path.join(ROOT, config.DATA_DIR)

    duka_path = os.path.join(data_dir, f"{symbol}_dukascopy.csv")
    mt5_path  = os.path.join(data_dir, f"{symbol}_M5.csv")

    if not os.path.exists(duka_path):
        logger.error(f"File Dukascopy non trovato: {duka_path}")
        return
    if not os.path.exists(mt5_path):
        logger.warning(f"File MT5 non trovato: {mt5_path} — uso solo Dukascopy")

    dfs = []

    df_duka = pd.read_csv(duka_path, index_col="datetime", parse_dates=True)
    df_duka.columns = [c.lower() for c in df_duka.columns]
    dfs.append(df_duka)

    if os.path.exists(mt5_path):
        df_mt5 = pd.read_csv(mt5_path, index_col="datetime", parse_dates=True)
        df_mt5.columns = [c.lower() for c in df_mt5.columns]
        df_mt5 = df_mt5[["open", "high", "low", "close", "volume"]]
        dfs.append(df_mt5)

    combined = pd.concat(dfs).sort_index()
    combined = combined[~combined.index.duplicated(keep="last")]
    combined = combined[["open", "high", "low", "close", "volume"]]

    out_path = os.path.join(data_dir, f"{symbol}_M5.csv")
    combined.index.name = "datetime"
    combined.to_csv(out_path)

    logger.info(f"\n  MERGE {symbol} completato:")
    logger.info(f"  Candele totali: {len(combined):,}")
    logger.info(f"  Periodo: {combined.index[0]} → {combined.index[-1]}")
    logger.info(f"  Salvato in: {out_path}")


# ─── MAIN ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    start = time.time()

    for sym in config.SYMBOLS:
        download_symbol(sym)
        merge_with_mt5(sym)

    elapsed = time.time() - start
    logger.info(f"\nCompletato in {elapsed/60:.1f} minuti")
    logger.info("Aggiorna TRAIN_CUTOFF_DATE in config.py se necessario, poi ri-esegui train.py")
