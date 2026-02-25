#!/usr/bin/env python3
"""
Dukascopy Downloader — iPhone Edition
======================================
Solo stdlib Python: urllib, lzma, struct, csv
Compatibile con: a-Shell, iSH, Pythonista

Uso:
    python3 dukascopy_iphone.py

Output: XAUUSD_M5.csv  (stesso formato del sistema)

Resume automatico: se il file esiste, continua dall'ultima data.
"""

import csv
import lzma
import os
import struct
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from collections import defaultdict

# ─── CONFIGURAZIONE ────────────────────────────────────────────────────────────

SYMBOL      = "XAUUSD"
DATE_START  = datetime(2020, 1, 1,  tzinfo=timezone.utc)
DATE_END    = datetime(2025, 12, 31, tzinfo=timezone.utc)
OUTPUT_FILE = f"{SYMBOL}_M5.csv"
PRICE_DIV   = 1000      # XAUUSD: prezzo intero / 1000
BAR_MINS    = 5         # aggregazione M5
RETRY       = 3
TIMEOUT     = 30
DELAY       = 0.05      # pausa tra richieste (iPhone: no multi-thread)

# ─── DOWNLOAD ──────────────────────────────────────────────────────────────────

def download_hour(dt: datetime):
    """Scarica 1 ora di tick. Ritorna lista di (timestamp_utc, mid_price)."""
    # mese 0-indexed in Dukascopy
    url = (
        f"https://datafeed.dukascopy.com/datafeed/{SYMBOL}/"
        f"{dt.year}/{dt.month - 1:02d}/{dt.day:02d}/{dt.hour:02d}h_ticks.bi5"
    )
    for attempt in range(RETRY):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                raw_gz = resp.read()

            if not raw_gz:
                return []

            raw = lzma.decompress(raw_gz)
            n   = len(raw) // 20
            ticks = []
            for i in range(n):
                ms, ask, bid, _, _ = struct.unpack(">IIIff", raw[i * 20: i * 20 + 20])
                ts  = dt + timedelta(milliseconds=int(ms))
                mid = (ask + bid) / 2 / PRICE_DIV
                ticks.append((ts, mid))
            return ticks

        except urllib.error.HTTPError as e:
            if e.code == 404:
                return []   # ora vuota (notte/weekend)
            time.sleep(2 ** attempt)
        except Exception:
            time.sleep(2 ** attempt)
    return []

# ─── AGGREGAZIONE M5 ───────────────────────────────────────────────────────────

def ticks_to_m5(ticks):
    """Aggrega tick in candele M5. Input: [(datetime, price), ...]"""
    bars = defaultdict(list)
    for ts, price in ticks:
        # arrotonda al bar M5 precedente
        floored = ts.replace(second=0, microsecond=0)
        mins    = floored.minute - (floored.minute % BAR_MINS)
        bar_ts  = floored.replace(minute=mins)
        bars[bar_ts].append(price)

    result = {}
    for bar_ts, prices in bars.items():
        result[bar_ts] = {
            "open":   prices[0],
            "high":   max(prices),
            "low":    min(prices),
            "close":  prices[-1],
            "volume": len(prices),
        }
    return result

# ─── RESUME: legge ultima data dal CSV ─────────────────────────────────────────

def get_last_date(filepath):
    """Ritorna l'ultima datetime nel CSV, o None se il file non esiste."""
    if not os.path.exists(filepath):
        return None
    last = None
    with open(filepath, "r") as f:
        reader = csv.reader(f)
        for row in reader:
            if row and row[0] != "datetime":
                try:
                    last = datetime.fromisoformat(row[0]).replace(tzinfo=timezone.utc)
                except ValueError:
                    pass
    return last

# ─── SCRITTURA CSV ─────────────────────────────────────────────────────────────

def write_bars(bars, filepath, append=False):
    mode = "a" if append else "w"
    with open(filepath, mode, newline="") as f:
        writer = csv.writer(f)
        if not append:
            writer.writerow(["datetime", "open", "high", "low", "close", "volume"])
        for ts in sorted(bars.keys()):
            b = bars[ts]
            writer.writerow([
                ts.strftime("%Y-%m-%d %H:%M:%S"),
                f"{b['open']:.3f}",
                f"{b['high']:.3f}",
                f"{b['low']:.3f}",
                f"{b['close']:.3f}",
                b["volume"],
            ])

# ─── MAIN ──────────────────────────────────────────────────────────────────────

def main():
    print(f"Dukascopy iPhone Downloader — {SYMBOL} M{BAR_MINS}")
    print(f"Output: {OUTPUT_FILE}")

    # Resume check
    last = get_last_date(OUTPUT_FILE)
    if last:
        start = last.replace(minute=0, second=0, microsecond=0)
        print(f"Resume da: {start}")
        append_mode = True
    else:
        start = DATE_START
        append_mode = False

    # Genera lista ore
    hours = []
    dt = start
    while dt <= DATE_END:
        if dt.weekday() != 6:  # salta domeniche
            hours.append(dt)
        dt += timedelta(hours=1)

    total = len(hours)
    print(f"Ore da scaricare: {total:,}\n")

    accumulated = {}
    written     = 0
    flush_every = 24  # scrivi su disco ogni 24 ore (1 giorno)

    for i, hour_dt in enumerate(hours, 1):
        ticks = download_hour(hour_dt)
        if ticks:
            bars = ticks_to_m5(ticks)
            accumulated.update(bars)

        # Progress ogni 100 ore
        if i % 100 == 0 or i == total:
            pct = i / total * 100
            print(f"  {i:,}/{total:,} ({pct:.1f}%) — {hour_dt.date()} — bars: {len(accumulated):,}")

        # Flush su disco ogni giorno (evita perdite su crash iPhone)
        if len(accumulated) >= flush_every * 12:  # ~12 bar/ora * 24h
            write_bars(accumulated, OUTPUT_FILE, append=append_mode)
            written    += len(accumulated)
            accumulated = {}
            append_mode = True

        time.sleep(DELAY)

    # Flush finale
    if accumulated:
        write_bars(accumulated, OUTPUT_FILE, append=append_mode)
        written += len(accumulated)

    print(f"\nCompletato! Candele totali scritte: {written:,}")
    print(f"File: {OUTPUT_FILE}")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrotto. Riavvia per continuare (resume automatico).")
        sys.exit(0)
