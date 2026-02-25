#!/usr/bin/env python3
"""
M1 → M5 Converter per PC
==========================
Converte i ZIP scaricati da HistData (MetaTrader .hst OPPURE CSV ASCII)
da M1 a M5 e salva i CSV in trading_system/data/.

Prerequisiti:
    pip install pandas

Uso:
    python m1_to_m5_pc.py C:\\Users\\TuoNome\\Downloads\\HistData
    python m1_to_m5_pc.py /home/user/Downloads/HistData

    (senza argomenti cerca nella cartella corrente)

Output:
    trading_system/data/EURUSD_M5.csv
    trading_system/data/XAUUSD_M5.csv

Formati supportati nei ZIP:
  - MetaTrader .hst  (versione 400 e 401)
  - HistData CSV/TXT (separatore ; oppure ,)
"""

import os
import struct
import sys
import zipfile
from datetime import datetime
from pathlib import Path

try:
    import pandas as pd
except ImportError:
    print("pandas non trovato. Installa con:\n    pip install pandas")
    sys.exit(1)

# ── Configurazione ─────────────────────────────────────────────────────────────
PAIRS = ["EURUSD", "XAUUSD"]
SCRIPT_DIR = Path(__file__).parent
OUT_DIR = SCRIPT_DIR / "trading_system" / "data"
# ──────────────────────────────────────────────────────────────────────────────


# ── Parser HST (MetaTrader binario) ───────────────────────────────────────────
def parse_hst(data: bytes) -> list:
    """Legge file .hst MetaTrader v400 o v401. Ritorna lista (datetime, O, H, L, C, V)."""
    if len(data) < 148:
        return []
    version = struct.unpack_from("<i", data, 0)[0]

    if version == 400:
        # Record 44 bytes: time(i4) open(d8) low(d8) high(d8) close(d8) vol(q8)
        rec_fmt, rec_size = "<iddddq", 44
        I_TS, I_O, I_H, I_L, I_C, I_V = 0, 1, 3, 2, 4, 5
    elif version == 401:
        # Record 60 bytes: time(q8) open(d8) high(d8) low(d8) close(d8) tvol(q8) spread(i4) rvol(q8)
        rec_fmt, rec_size = "<qddddqiq", 60
        I_TS, I_O, I_H, I_L, I_C, I_V = 0, 1, 2, 3, 4, 5
    else:
        print(f"    Versione .hst non supportata: {version}")
        return []

    body = data[148:]
    n = (len(body) // rec_size) * rec_size
    records = []
    for row in struct.iter_unpack(rec_fmt, body[:n]):
        ts = datetime.utcfromtimestamp(row[I_TS])
        records.append((ts, row[I_O], row[I_H], row[I_L], row[I_C], int(row[I_V])))
    return records


# ── Parser CSV ASCII (formato HistData) ───────────────────────────────────────
def parse_histdata_csv(data: bytes) -> list:
    """
    Legge CSV ASCII di HistData. Formati supportati:
      20200103 170200;1.12133;1.12147;1.12130;1.12136;70    (spazio come sep data/ora)
      20200103,170200,1.12133,1.12147,1.12130,1.12136,70    (virgola)
      2020.01.03,17:02:00,1.12133,1.12147,1.12130,1.12136,70
    """
    records = []
    text = data.decode("utf-8", errors="ignore")
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        # Normalizza in virgole
        line = line.replace(";", ",").replace(" ", ",")
        parts = line.split(",")
        if len(parts) < 6:
            continue
        try:
            # Normalizza data: rimuovi punti (2020.01.03 -> 20200103)
            date_str = parts[0].replace(".", "")
            # Normalizza ora: rimuovi i due punti (17:02:00 -> 170200)
            time_str = parts[1].replace(":", "").ljust(6, "0")[:6]
            ts = datetime.strptime(date_str + time_str, "%Y%m%d%H%M%S")
            o = float(parts[2])
            h = float(parts[3])
            l = float(parts[4])
            c = float(parts[5])
            v = int(float(parts[6])) if len(parts) > 6 else 0
            records.append((ts, o, h, l, c, v))
        except (ValueError, IndexError):
            continue
    return records


# ── Trova file nella cartella ──────────────────────────────────────────────────
def find_files(folder: Path, pair: str):
    """Cerca ricorsivamente ZIP, HST e CSV col nome del pair."""
    zips, hsts, csvs = [], [], []
    for path in sorted(folder.rglob("*")):
        if not path.is_file():
            continue
        nl = path.name.lower()
        if pair.lower() not in nl:
            continue
        if nl.endswith(".zip"):
            zips.append(path)
        elif nl.endswith(".hst"):
            hsts.append(path)
        elif nl.endswith((".csv", ".txt")):
            csvs.append(path)
    return zips, hsts, csvs


def process_zip(zip_path: Path) -> list:
    """Estrae e converte tutti i file .hst / .csv dentro uno ZIP."""
    records = []
    try:
        with zipfile.ZipFile(zip_path) as z:
            for name in sorted(z.namelist()):
                nl = name.lower()
                with z.open(name) as f:
                    data = f.read()
                if nl.endswith(".hst"):
                    r = parse_hst(data)
                    if r:
                        print(f"      .hst {name}: {len(r):,} barre M1")
                    records.extend(r)
                elif nl.endswith((".csv", ".txt")):
                    r = parse_histdata_csv(data)
                    if r:
                        print(f"      .csv {name}: {len(r):,} barre M1")
                    records.extend(r)
    except zipfile.BadZipFile:
        print(f"    File ZIP corrotto: {zip_path.name}")
    except Exception as e:
        print(f"    Errore {zip_path.name}: {e}")
    return records


# ── Conversione M1 → M5 con pandas ────────────────────────────────────────────
def records_to_df(records: list) -> pd.DataFrame:
    df = pd.DataFrame(records, columns=["datetime", "open", "high", "low", "close", "volume"])
    df["datetime"] = pd.to_datetime(df["datetime"])
    df = df.set_index("datetime").sort_index()
    df = df[~df.index.duplicated(keep="first")]
    return df


def m1_to_m5(df: pd.DataFrame) -> pd.DataFrame:
    """Resample da M1 a M5."""
    return (
        df.resample("5min")
        .agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})
        .dropna(subset=["open"])
    )


# ── Main ───────────────────────────────────────────────────────────────────────
def main():
    folder = Path(sys.argv[1]).expanduser().resolve() if len(sys.argv) > 1 else Path.cwd()

    print(f"Sorgente  : {folder}")
    print(f"Output    : {OUT_DIR}\n")

    if not folder.exists():
        print(f"ERRORE: cartella non trovata: {folder}")
        sys.exit(1)

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    for pair in PAIRS:
        print(f"{'='*60}")
        print(f"  {pair}")
        print(f"{'='*60}")

        zips, hsts, csvs = find_files(folder, pair)

        if not any([zips, hsts, csvs]):
            print(f"  Nessun file trovato per {pair} in:\n  {folder}\n")
            continue

        all_records = []

        for z in zips:
            print(f"  ZIP  {z.name}")
            all_records.extend(process_zip(z))

        for h in hsts:
            print(f"  HST  {h.name} ...", end=" ", flush=True)
            r = parse_hst(h.read_bytes())
            print(f"{len(r):,} barre M1")
            all_records.extend(r)

        for c in csvs:
            print(f"  CSV  {c.name} ...", end=" ", flush=True)
            r = parse_histdata_csv(c.read_bytes())
            print(f"{len(r):,} barre M1")
            all_records.extend(r)

        if not all_records:
            print("  Nessun dato M1 trovato.\n")
            continue

        print(f"\n  M1 totale grezzo : {len(all_records):,} barre")

        df = records_to_df(all_records)
        print(f"  Dopo dedup       : {len(df):,} barre")
        print(f"  Range            : {df.index[0]}  →  {df.index[-1]}")

        print(f"  Converto M1 → M5 ...", end=" ", flush=True)
        m5 = m1_to_m5(df)
        print(f"{len(m5):,} barre M5")

        out = OUT_DIR / f"{pair}_M5.csv"
        m5.to_csv(out, date_format="%Y-%m-%d %H:%M:%S")
        print(f"  Salvato: {out}\n")

    print("Fatto.")


if __name__ == "__main__":
    main()
