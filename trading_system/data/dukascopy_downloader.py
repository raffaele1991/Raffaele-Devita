"""
Dukascopy Historical Data Downloader — TURBO
=============================================
Ottimizzazioni rispetto alla versione base:
  1. Tutti i simboli scaricati in parallelo nello stesso pool (non sequenziali)
  2. Aggregazione tick→M5 inline nel worker (zero pandas per ora, ~100x meno RAM)
  3. WORKERS=60, HTTPAdapter pool_maxsize=80 (connessioni realmente parallele)
  4. TIMEOUT=12 (fail veloce sulle ore vuote che tardano a rispondere)
  5. struct.Struct cached + iter_unpack (no slicing per tick)
  6. Bar bucket calcolato con aritmetica intera (no datetime.replace per tick)
  7. Nessun pd.concat di milioni di tick — accumulo dict leggero

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

DATE_END = datetime.now(tz=timezone.utc).replace(hour=23, minute=59, second=59)

WORKERS = 60   # thread paralleli — tutti i simboli insieme
RETRY   = 2    # tentativi per ora fallita
TIMEOUT = 12   # secondi: fail veloce sulle ore vuote

# ─── HTTP SESSION con pool grande ──────────────────────────────────────────────

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "Mozilla/5.0"})
_adapter = HTTPAdapter(pool_connections=80, pool_maxsize=80, max_retries=0)
SESSION.mount("https://", _adapter)

# Struct pre-compilato: evita ri-parsing del formato ad ogni chiamata
_TICK = struct.Struct(">IIIff")
_5MIN_MS = 300_000  # 5 minuti in millisecondi


# ─── WORKER: download + aggregazione M5 inline ─────────────────────────────────

def download_hour(symbol: str, dt: datetime) -> dict:
    """
    Scarica 1 ora di tick e aggrega inline in barre M5.
    Ritorna dict {bar_datetime: [O, H, L, C, tick_count]} — vuoto se nessun dato.
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

            # Ora di inizio in ms epoch — per calcolare bar_ts senza datetime.replace
            hour_epoch_ms = int(dt.timestamp() * 1000)

            bars: dict = {}
            for ms_raw, ask_i, bid_i, _, _ in _TICK.iter_unpack(raw):
                mid = (ask_i + bid_i) / 2 / divisor
                # Bar bucket: arrotonda ms al multiplo di 5 min precedente
                bar_epoch_ms = (hour_epoch_ms + int(ms_raw)) // _5MIN_MS * _5MIN_MS
                b = bars.get(bar_epoch_ms)
                if b is None:
                    bars[bar_epoch_ms] = [mid, mid, mid, mid, 1]
                else:
                    if mid > b[1]: b[1] = mid  # H
                    if mid < b[2]: b[2] = mid  # L
                    b[3] = mid                 # C
                    b[4] += 1                  # volume (tick count)

            return bars

        except lzma.LZMAError:
            return {}
        except Exception:
            if attempt < RETRY - 1:
                time.sleep(2 ** attempt)

    return {}


# ─── MERGE BARRE IN MEMORIA ────────────────────────────────────────────────────

def _merge_into(target: dict, source: dict) -> None:
    """Merges source bars into target in-place (chiamato dal main thread)."""
    for key, (o, h, l, c, v) in source.items():
        b = target.get(key)
        if b is None:
            target[key] = [o, h, l, c, v]
        else:
            if h > b[1]: b[1] = h
            if l < b[2]: b[2] = l
            b[3] = c
            b[4] += v


# ─── CONVERSIONE BARS DICT → DATAFRAME ─────────────────────────────────────────

def _bars_to_df(bars: dict) -> pd.DataFrame:
    rows = sorted(bars.items())
    df = pd.DataFrame(
        [(datetime.utcfromtimestamp(k / 1000).replace(tzinfo=timezone.utc),
          o, h, l, c, v)
         for k, (o, h, l, c, v) in rows],
        columns=["datetime", "open", "high", "low", "close", "volume"],
    ).set_index("datetime")
    return df


# ─── SALVATAGGIO CSV ───────────────────────────────────────────────────────────

def _save_dukascopy(symbol: str, bars: dict) -> str:
    out_path = os.path.join(ROOT, config.DATA_DIR, f"{symbol}_dukascopy.csv")
    df = _bars_to_df(bars)
    df.index.name = "datetime"
    df.to_csv(out_path)
    logger.info(f"  {symbol}: {len(df):,} candele M5 → {out_path}")
    return out_path


# ─── MERGE CON DATI MT5 ESISTENTI ─────────────────────────────────────────────

def merge_with_mt5(symbol: str) -> None:
    data_dir  = os.path.join(ROOT, config.DATA_DIR)
    duka_path = os.path.join(data_dir, f"{symbol}_dukascopy.csv")
    mt5_path  = os.path.join(data_dir, f"{symbol}_M5.csv")

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
        os.path.join(data_dir, f"{symbol}_M5.csv"), index_label="datetime"
    )
    logger.info(f"  MERGE {symbol}: {len(combined):,} candele → {mt5_path}")


# ─── MAIN ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    t0 = time.time()

    symbols = list(config.SYMBOLS)

    # Costruisce lista (symbol, hour_dt) per tutti i simboli insieme
    all_jobs: list[tuple[str, datetime]] = []
    for sym in symbols:
        start = SYMBOL_START.get(sym, datetime(2003, 5, 1, tzinfo=timezone.utc))
        dt = start
        while dt <= DATE_END:
            if dt.weekday() != 6:   # salta domeniche
                all_jobs.append((sym, dt))
            dt += timedelta(hours=1)

    total = len(all_jobs)
    logger.info(f"\n{'='*60}")
    logger.info(f"  TURBO Dukascopy — {len(symbols)} simboli in parallelo")
    logger.info(f"  Ore totali da scaricare: {total:,}  |  Worker: {WORKERS}")
    logger.info(f"  Stima: ~{total / WORKERS * 0.4 / 60:.0f} min")
    logger.info(f"{'='*60}\n")

    # Accumulatori M5 per simbolo (dict leggeri, niente DataFrame in volo)
    bars_by_symbol: dict[str, dict] = {sym: {} for sym in symbols}
    done = 0

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = {
            pool.submit(download_hour, sym, h): sym
            for sym, h in all_jobs
        }
        for fut in as_completed(futures):
            sym  = futures[fut]
            data = fut.result()
            if data:
                _merge_into(bars_by_symbol[sym], data)
            done += 1
            if done % 5_000 == 0:
                pct = done / total * 100
                eta = (total - done) / WORKERS * 0.4 / 60
                logger.info(f"  {done:,}/{total:,}  ({pct:.1f}%)  ETA≈{eta:.0f}min")

    logger.info("\nDownload completato — salvataggio CSV...")

    for sym in symbols:
        if not bars_by_symbol[sym]:
            logger.error(f"  Nessun dato per {sym}")
            continue
        _save_dukascopy(sym, bars_by_symbol[sym])
        merge_with_mt5(sym)

    elapsed = (time.time() - t0) / 60
    logger.info(f"\nCompletato in {elapsed:.1f} minuti")
    logger.info("Aggiorna TRAIN_CUTOFF_DATE in config.py se necessario, poi ri-esegui train.py")
