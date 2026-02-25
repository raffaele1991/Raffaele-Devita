#!/usr/bin/env python3
"""
HistData Converter — iPhone Edition
=====================================
Converte i ZIP scaricati manualmente da HistData (MetaTrader .hst)
in CSV M5 pronti per il trading system.

NON serve pip install — usa solo la libreria standard Python.

ISTRUZIONI:
  1. Vai su Safari e scarica i 12 ZIP da HistData:
       EURUSD: https://www.histdata.com/download-free-forex-historical-data/?/metatrader/1-minute-bar-quotes/EURUSD
       XAUUSD: https://www.histdata.com/download-free-forex-historical-data/?/metatrader/1-minute-bar-quotes/XAUUSD
     Clicca anni 2020 2021 2022 2023 2024 2025 per entrambe (12 ZIP totali).

  2. Nell'app File, sposta tutti i 12 ZIP in una cartella, es: "Downloads"

  3. In a-Shell, imposta la cartella qui sotto e avvia:
       python3 histdata_convert.py

OUTPUT: EURUSD_M5_2020_2025.csv e XAUUSD_M5_2020_2025.csv
        nella stessa cartella dei ZIP.
"""

import csv
import os
import struct
import zipfile
from datetime import datetime

# ── CARTELLA ZIP: argomento da riga di comando oppure default ─────────────────
import sys
ZIP_FOLDER = os.path.expanduser(sys.argv[1]) if len(sys.argv) > 1 else os.path.expanduser("~/Downloads")
# ─────────────────────────────────────────────────────────────────────────────


def parse_hst(data: bytes) -> list:
    """Legge file .hst MetaTrader v400 o v401, ritorna lista (datetime, O, H, L, C, V)."""
    if len(data) < 148:
        return []
    version = struct.unpack_from("<i", data, 0)[0]

    if version == 400:
        # Record 44 bytes: time(i4) open(d8) low(d8) high(d8) close(d8) vol(q8)
        rec_fmt, rec_size = "<iddddq", 44
        I_TS, I_O, I_L, I_H, I_C, I_V = 0, 1, 2, 3, 4, 5
    elif version == 401:
        # Record 60 bytes: time(q8) open(d8) high(d8) low(d8) close(d8) tvol(q8) spread(i4) rvol(q8)
        rec_fmt, rec_size = "<qddddqiq", 60
        I_TS, I_O, I_H, I_L, I_C, I_V = 0, 1, 2, 3, 4, 5
    else:
        print(f"    Versione .hst non supportata: {version}")
        return []

    records = []
    offset = 148
    while offset + rec_size <= len(data):
        row = struct.unpack_from(rec_fmt, data, offset)
        ts = datetime.utcfromtimestamp(row[I_TS])
        records.append((ts, row[I_O], row[I_H], row[I_L], row[I_C], row[I_V]))
        offset += rec_size
    return records


def m1_to_m5(records: list) -> list:
    """Aggrega barre M1 in M5 (OHLCV). Input già ordinato per timestamp."""
    bars = {}
    for ts, o, h, l, c, v in records:
        key = ts.replace(second=0, microsecond=0,
                         minute=(ts.minute // 5) * 5)
        if key not in bars:
            bars[key] = [o, h, l, c, int(v)]
        else:
            if h > bars[key][1]: bars[key][1] = h
            if l < bars[key][2]: bars[key][2] = l
            bars[key][3] = c
            bars[key][4] += int(v)
    return sorted(bars.items())


def process_zip(zip_path: str) -> list:
    """Estrae e converte tutti gli .hst dentro uno ZIP."""
    all_records = []
    try:
        with zipfile.ZipFile(zip_path) as z:
            hst_files = [n for n in z.namelist() if n.lower().endswith(".hst")]
            if not hst_files:
                print(f"    Nessun .hst in {os.path.basename(zip_path)}")
                return []
            for name in hst_files:
                with z.open(name) as f:
                    data = f.read()
                records = parse_hst(data)
                all_records.extend(records)
    except Exception as e:
        print(f"    Errore ZIP {os.path.basename(zip_path)}: {e}")
    return all_records


def collect_hst_files(folder: str, pair: str) -> tuple:
    """
    Cerca ricorsivamente nella cartella:
    - file .zip contenenti .hst  (ZIP non estratti)
    - file .hst direttamente nelle sottocartelle (ZIP già estratti da iOS)
    Ritorna (lista_zip, lista_hst_diretti)
    """
    zips, hsts = [], []
    for root, dirs, files in os.walk(folder):
        dirs.sort()
        for fname in sorted(files):
            fl = fname.lower()
            path = os.path.join(root, fname)
            if pair.lower() in fl:
                if fl.endswith(".zip"):
                    zips.append(path)
                elif fl.endswith(".hst"):
                    hsts.append(path)
    return zips, hsts


def save_csv(bars: list, out_path: str):
    with open(out_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["datetime", "open", "high", "low", "close", "volume"])
        for ts, (o, h, l, c, v) in bars:
            w.writerow([ts.strftime("%Y-%m-%d %H:%M:%S"),
                        f"{o:.5f}", f"{h:.5f}", f"{l:.5f}", f"{c:.5f}", v])


def main():
    print(f"Cartella: {ZIP_FOLDER}\n")

    for pair in ["EURUSD", "XAUUSD"]:
        print(f"{'='*50}\n  {pair}\n{'='*50}")

        zips, hsts = collect_hst_files(ZIP_FOLDER, pair)
        if not zips and not hsts:
            print(f"  Nessun file trovato per {pair}")
            print(f"  (cerca .zip o .hst con '{pair}' nel nome, anche in sottocartelle)\n")
            continue

        all_records = []

        for z in zips:
            print(f"  ZIP  {os.path.basename(z)} ...", end=" ", flush=True)
            records = process_zip(z)
            print(f"{len(records):,} barre M1")
            all_records.extend(records)

        for h in hsts:
            print(f"  HST  {os.path.basename(h)} ...", end=" ", flush=True)
            with open(h, "rb") as f:
                data = f.read()
            records = parse_hst(data)
            print(f"{len(records):,} barre M1")
            all_records.extend(records)

        if not all_records:
            print("  Nessun dato trovato.\n")
            continue

        # Ordina e rimuovi duplicati
        all_records.sort(key=lambda x: x[0])
        seen = set()
        unique = []
        for r in all_records:
            if r[0] not in seen:
                seen.add(r[0])
                unique.append(r)

        print(f"  Totale M1: {len(unique):,} barre")
        print(f"  Converto M1 -> M5 ...", end=" ", flush=True)

        m5 = m1_to_m5(unique)
        print(f"{len(m5):,} barre M5")

        out = os.path.join(ZIP_FOLDER, f"{pair}_M5_2020_2025.csv")
        save_csv(m5, out)
        print(f"  Salvato: {out}")
        print(f"  Da {m5[0][0]}  a  {m5[-1][0]}\n")


if __name__ == "__main__":
    main()
