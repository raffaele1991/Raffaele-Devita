#!/usr/bin/env python3
"""
Dukascopy Downloader — Termux / Phone Edition
==============================================
Solo stdlib Python: urllib, lzma, struct, csv, os, time
Compatibile con: Termux (Android), a-Shell (iOS), iSH, Pythonista

Uso base:
    python3 dukascopy_iphone.py                 # scarica tutti i simboli
    python3 dukascopy_iphone.py EURUSD          # solo un simbolo
    python3 dukascopy_iphone.py EURUSD XAUUSD   # simboli specifici

Output:
    ./duka_data/EURUSD_M5.csv
    ./duka_data/EURUSD_progress.txt   ← file di resume automatico

Resume automatico:
    Se interrompi con Ctrl+C (o si scarica la batteria), riavvia lo stesso
    comando. Il download riparte dall'ultimo giorno completato.

Stima tempi per simbolo (20 anni):
    ~4-6 ore in background su Termux (nohup python3 dukascopy_iphone.py EURUSD &)
"""

import csv
import lzma
import os
import struct
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timedelta, timezone
from collections import defaultdict

# ─── SIMBOLI E DIVISORI PREZZO ────────────────────────────────────────────────
# Dukascopy codifica i prezzi come interi; bisogna dividere per:
#   100000  → coppie forex a 5 decimali  (es. EURUSD: 112345 → 1.12345)
#   1000    → JPY e Gold a 3 decimali    (es. USDJPY: 156789 → 156.789)

SYMBOLS = {
    "EURUSD": 100000,
    "GBPUSD": 100000,
    "USDJPY": 1000,
    "USDCHF": 100000,
    "AUDUSD": 100000,
    "NZDUSD": 100000,
    "USDCAD": 100000,
    "EURJPY": 1000,
    "GBPJPY": 1000,
    "XAUUSD": 1000,
}

# Data inizio per simbolo (prima data disponibile su Dukascopy)
SYMBOL_START = {
    "EURUSD": datetime(2003,  5,  4, tzinfo=timezone.utc),
    "GBPUSD": datetime(2003,  5,  4, tzinfo=timezone.utc),
    "USDJPY": datetime(2003,  5,  4, tzinfo=timezone.utc),
    "USDCHF": datetime(2003,  5,  4, tzinfo=timezone.utc),
    "AUDUSD": datetime(2003,  5,  4, tzinfo=timezone.utc),
    "NZDUSD": datetime(2004,  1,  4, tzinfo=timezone.utc),
    "USDCAD": datetime(2004,  1,  4, tzinfo=timezone.utc),
    "EURJPY": datetime(2003,  5,  4, tzinfo=timezone.utc),
    "GBPJPY": datetime(2003,  5,  4, tzinfo=timezone.utc),
    "XAUUSD": datetime(2003,  8,  4, tzinfo=timezone.utc),
}

DATE_END   = datetime(2025, 12, 31, tzinfo=timezone.utc)
BAR_MINS   = 5          # aggregazione M5
RETRY      = 3          # tentativi per richiesta fallita
TIMEOUT    = 30         # secondi timeout HTTP
DELAY      = 0.12       # pausa tra richieste (sec) — non scendere sotto 0.1
OUTPUT_DIR = "duka_data"

# ─── DOWNLOAD SINGOLA ORA ─────────────────────────────────────────────────────

def download_hour(symbol: str, price_div: int, dt: datetime):
    """
    Scarica 1 ora di tick da Dukascopy.
    Ritorna lista di (datetime_utc, ask, bid, ask_vol, bid_vol) o [] se vuota.
    """
    # Nota: Dukascopy usa mesi 0-indexed (gennaio = 00)
    url = (
        f"https://datafeed.dukascopy.com/datafeed/{symbol}/"
        f"{dt.year}/{dt.month - 1:02d}/{dt.day:02d}/{dt.hour:02d}h_ticks.bi5"
    )
    headers = {"User-Agent": "Mozilla/5.0 (Linux; Android 12) AppleWebKit/537.36"}

    for attempt in range(RETRY):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                raw_gz = resp.read()

            if not raw_gz:
                return []

            raw = lzma.decompress(raw_gz)
            n   = len(raw) // 20
            ticks = []
            for i in range(n):
                ms, ask_i, bid_i, ask_vol, bid_vol = struct.unpack(
                    ">IIIff", raw[i * 20: i * 20 + 20]
                )
                ts      = dt + timedelta(milliseconds=int(ms))
                ask     = ask_i   / price_div
                bid     = bid_i   / price_div
                ticks.append((ts, ask, bid, float(ask_vol), float(bid_vol)))
            return ticks

        except urllib.error.HTTPError as e:
            if e.code == 404:
                return []   # ora vuota: weekend, notte, festivo
            time.sleep(2 ** attempt)
        except urllib.error.URLError:
            time.sleep(2 ** attempt)
        except lzma.LZMAError:
            return []       # file corrotto
        except Exception:
            time.sleep(2 ** attempt)

    return []


# ─── AGGREGAZIONE M5 ──────────────────────────────────────────────────────────

def ticks_to_m5(ticks):
    """
    Aggrega tick in candele M5.
    Input:  [(datetime, ask, bid, ask_vol, bid_vol), ...]
    Output: {bar_datetime: [open, high, low, close, volume], ...}
    Volume = somma (ask_vol + bid_vol) / 2 per tick
    """
    bars = {}
    for ts, ask, bid, ask_vol, bid_vol in ticks:
        mid = (ask + bid) / 2
        vol = (ask_vol + bid_vol) / 2

        # Arrotonda al multiplo di BAR_MINS precedente
        floored = ts.replace(second=0, microsecond=0)
        mins    = floored.minute - (floored.minute % BAR_MINS)
        bar_ts  = floored.replace(minute=mins)

        if bar_ts not in bars:
            bars[bar_ts] = [mid, mid, mid, mid, vol]    # O H L C V
        else:
            if mid > bars[bar_ts][1]: bars[bar_ts][1] = mid   # H
            if mid < bars[bar_ts][2]: bars[bar_ts][2] = mid   # L
            bars[bar_ts][3] = mid                              # C
            bars[bar_ts][4] += vol                             # V

    return bars


# ─── RESUME: file di progresso separato (veloce anche su CSV grandi) ──────────

def progress_file(symbol):
    return os.path.join(OUTPUT_DIR, f"{symbol}_progress.txt")

def load_progress(symbol):
    """Ritorna l'ultimo giorno completato (datetime) o None."""
    pf = progress_file(symbol)
    if not os.path.exists(pf):
        return None
    try:
        with open(pf) as f:
            line = f.read().strip()
        if line:
            return datetime.strptime(line, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except Exception:
        pass
    return None

def save_progress(symbol, date: datetime):
    with open(progress_file(symbol), "w") as f:
        f.write(date.strftime("%Y-%m-%d"))


# ─── SCRITTURA CSV ────────────────────────────────────────────────────────────

def write_bars(bars: dict, filepath: str, append: bool):
    mode = "a" if append else "w"
    with open(filepath, mode, newline="") as f:
        writer = csv.writer(f)
        if not append:
            writer.writerow(["datetime", "open", "high", "low", "close", "volume"])
        for ts in sorted(bars.keys()):
            o, h, l, c, v = bars[ts]
            fmt = ".5f" if o < 100 else ".3f"    # 5 dec forex, 3 dec gold/JPY
            writer.writerow([
                ts.strftime("%Y-%m-%d %H:%M:%S"),
                format(o, fmt),
                format(h, fmt),
                format(l, fmt),
                format(c, fmt),
                f"{v:.2f}",
            ])


# ─── DOWNLOAD COMPLETO PER SIMBOLO ────────────────────────────────────────────

def download_symbol(symbol: str):
    price_div   = SYMBOLS[symbol]
    output_file = os.path.join(OUTPUT_DIR, f"{symbol}_M5.csv")

    # Determina punto di partenza
    last_done = load_progress(symbol)
    if last_done:
        start_date = last_done + timedelta(days=1)
        append     = True
        print(f"  RESUME da {start_date.date()}")
    else:
        start_date = SYMBOL_START.get(symbol, datetime(2003, 5, 4, tzinfo=timezone.utc))
        append     = os.path.exists(output_file)
        print(f"  Inizio da {start_date.date()}")

    if start_date > DATE_END:
        print(f"  Gia' completo fino a {DATE_END.date()}")
        return

    # Lista giorni da scaricare (escludi domeniche)
    days = []
    d = start_date.replace(hour=0, minute=0, second=0, microsecond=0)
    while d <= DATE_END:
        if d.weekday() != 6:   # 6 = domenica
            days.append(d)
        d += timedelta(days=1)

    total_days = len(days)
    print(f"  Giorni rimanenti: {total_days:,}  ({total_days // 252:.0f} anni)")
    print(f"  Stima tempo: {total_days * 24 * DELAY / 3600:.1f}h (in background)")
    print()

    # ── Loop principale: giorno per giorno ─────────────────────────────────────
    day_bars_total = 0

    for day_idx, day in enumerate(days, 1):
        day_ticks = []

        for hour in range(24):
            hour_dt = day.replace(hour=hour)
            ticks   = download_hour(symbol, price_div, hour_dt)
            day_ticks.extend(ticks)
            time.sleep(DELAY)

        # Aggrega e scrivi le candele del giorno
        day_bars = ticks_to_m5(day_ticks)
        if day_bars:
            write_bars(day_bars, output_file, append=append)
            append          = True
            day_bars_total += len(day_bars)

        # Salva progresso (resume sicuro)
        save_progress(symbol, day)

        # Aggiorna schermo ogni giorno (sovrascrive la riga)
        pct = day_idx / total_days * 100
        eta_h = (total_days - day_idx) * 24 * DELAY / 3600
        print(
            f"  {day.strftime('%Y-%m-%d')}  [{pct:5.1f}%]  "
            f"bar_oggi={len(day_bars):3d}  tot={day_bars_total:,}  "
            f"ETA≈{eta_h:.1f}h        ",
            end="\r", flush=True
        )

    print(f"\n  Completato! Candele totali: {day_bars_total:,} → {output_file}")


# ─── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # Simboli da riga di comando, o tutti se non specificato
    if len(sys.argv) > 1:
        requested = [s.upper() for s in sys.argv[1:]]
        unknown   = [s for s in requested if s not in SYMBOLS]
        if unknown:
            print(f"Simboli non riconosciuti: {unknown}")
            print(f"Simboli disponibili: {list(SYMBOLS.keys())}")
            sys.exit(1)
        to_download = {s: SYMBOLS[s] for s in requested}
    else:
        to_download = SYMBOLS

    print("=" * 60)
    print("  Dukascopy Downloader — Termux Edition")
    print(f"  Periodo: 2003 → {DATE_END.date()}")
    print(f"  Output:  {os.path.abspath(OUTPUT_DIR)}/")
    print(f"  Simboli: {list(to_download.keys())}")
    print("=" * 60)
    print()
    print("  Suggerimento per background:")
    print("  nohup python3 dukascopy_iphone.py EURUSD > eurusd.log 2>&1 &")
    print("  tail -f eurusd.log")
    print()

    for symbol in to_download:
        print(f"\n{'─'*50}")
        print(f"  Simbolo: {symbol}")
        print(f"{'─'*50}")
        download_symbol(symbol)

    print("\nTutti i simboli completati.")
    print(f"File CSV salvati in: {os.path.abspath(OUTPUT_DIR)}/")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nInterrotto. Riavvia per continuare (resume automatico).")
        sys.exit(0)
