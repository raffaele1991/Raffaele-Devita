#!/usr/bin/env python3
"""
HistData Downloader + M1->M5 Converter per iPhone (a-Shell)
============================================================
Scarica EURUSD e XAUUSD M1 (MetaTrader .hst o ASCII .csv)
e converte in M5 CSV. Totale: 12 ZIP (2 coppie x 6 anni).

INSTALLAZIONE:
    pip install requests beautifulsoup4 pandas

USO:
    python histdata_iphone.py

Output: ~/Documents/HistData_M5/  (visibile nell'app File iPhone)
"""

import requests
from bs4 import BeautifulSoup
import zipfile
import pandas as pd
import struct
import io
import os
import time

# ── Config ────────────────────────────────────────────────────────────────────
PAIRS  = ["EURUSD", "XAUUSD"]
YEARS  = range(2020, 2026)
OUTPUT = os.path.expanduser("~/Documents/HistData_M5")
os.makedirs(OUTPUT, exist_ok=True)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept":          "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}

# ── Token + form ──────────────────────────────────────────────────────────────

def get_form_data(session: requests.Session, pair: str, year: int) -> dict | None:
    """
    Prova prima MetaTrader (come mostrato sul sito), poi ASCII come fallback.
    Estrae TUTTI i campi hidden del form per evitare errori di token.
    """
    attempts = [
        ("metatrader", "MetaTrader"),
        ("ascii",      "ASCII"),
    ]
    for url_fmt, form_fmt in attempts:
        url = (
            f"https://www.histdata.com/download-free-forex-historical-data/"
            f"?/{url_fmt}/1-minute-bar-quotes/{pair}/{year}"
        )
        try:
            r = session.get(
                url,
                headers={**HEADERS, "Referer": "https://www.histdata.com/"},
                timeout=30
            )
            r.raise_for_status()
        except Exception as e:
            print(f"    GET [{url_fmt}] error: {e}")
            continue

        soup = BeautifulSoup(r.text, "html.parser")
        form = soup.find("form", {"id": "file_down"}) or soup.find("form")
        if not form:
            continue

        data = {
            inp.get("name"): inp.get("value", "")
            for inp in form.find_all("input")
            if inp.get("name")
        }

        if not data.get("tk"):
            continue

        # Sovrascriviamo con i valori corretti per anno intero
        data.update({
            "datemonth": "0",
            "date":      str(year),
            "platform":  form_fmt,
            "timeframe": "M1",
            "fxpair":    pair,
        })
        return data

    return None


def download_zip(session: requests.Session, pair: str, year: int, form_data: dict) -> bytes | None:
    fmt = form_data.get("platform", "?")
    ref = (
        f"https://www.histdata.com/download-free-forex-historical-data/"
        f"?/{fmt.lower()}/1-minute-bar-quotes/{pair}/{year}"
    )
    try:
        r = session.post(
            "https://www.histdata.com/get.php",
            data=form_data,
            headers={**HEADERS, "Referer": ref},
            timeout=120
        )
        r.raise_for_status()
        if len(r.content) < 2000:
            print(f"    Risposta troppo piccola ({len(r.content)} B)")
            return None
        return r.content
    except Exception as e:
        print(f"    POST error: {e}")
        return None


# ── Parser .hst (MetaTrader binario) ──────────────────────────────────────────

def parse_hst(data: bytes) -> pd.DataFrame | None:
    """
    Legge un file .hst MetaTrader 4/5 e restituisce un DataFrame OHLCV.
    Supporta version 400 (record 44 B) e 401 (record 60 B).
    """
    if len(data) < 148:
        return None
    version = struct.unpack_from("<i", data, 0)[0]

    if version == 400:
        # Header 148 B | Record: CTM(i4) O(d8) L(d8) H(d8) C(d8) VOL(q8) = 44 B
        rec_fmt  = "<iddddq"
        rec_size = 44
        hdr_size = 148
        fields   = ["ts", "Open", "Low", "High", "Close", "Volume"]
    elif version == 401:
        # Header 148 B | Record: CTM(q8) O(d8) H(d8) L(d8) C(d8) TV(q8) SP(i4) RV(q8) = 60 B
        rec_fmt  = "<qddddqiq"
        rec_size = 60
        hdr_size = 148
        fields   = ["ts", "Open", "High", "Low", "Close", "TickVol", "Spread", "RealVol"]
    else:
        print(f"    Versione .hst sconosciuta: {version}")
        return None

    n_records = (len(data) - hdr_size) // rec_size
    if n_records == 0:
        return None

    rows = []
    offset = hdr_size
    for _ in range(n_records):
        row = struct.unpack_from(rec_fmt, data, offset)
        rows.append(row)
        offset += rec_size

    df = pd.DataFrame(rows, columns=fields)
    df["DateTime"] = pd.to_datetime(df["ts"], unit="s", utc=True).dt.tz_localize(None)
    df = df.set_index("DateTime")

    # v401 ha H e L invertiti rispetto a v400 — normalizziamo
    if version == 401:
        df = df.rename(columns={"High": "H_tmp", "Low": "L_tmp"})
        df = df.rename(columns={"H_tmp": "High", "L_tmp": "Low"})

    return df[["Open", "High", "Low", "Close", "Volume"]].sort_index()


# ── Parser .csv (ASCII) ───────────────────────────────────────────────────────

def parse_csv(data: bytes) -> pd.DataFrame | None:
    try:
        df = pd.read_csv(
            io.BytesIO(data), sep=";", header=None,
            names=["Date", "Time", "Open", "High", "Low", "Close", "Volume"],
            dtype={"Date": str, "Time": str}
        )
        df["DateTime"] = pd.to_datetime(
            df["Date"] + " " + df["Time"],
            format="%Y%m%d %H%M%S", errors="coerce"
        )
        df = df.dropna(subset=["DateTime"]).set_index("DateTime").sort_index()
        for col in ["Open", "High", "Low", "Close", "Volume"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        return df[["Open", "High", "Low", "Close", "Volume"]].dropna()
    except Exception as e:
        print(f"    CSV parse error: {e}")
        return None


# ── ZIP -> DataFrame ──────────────────────────────────────────────────────────

def zip_to_dataframe(zip_bytes: bytes) -> pd.DataFrame | None:
    frames = []
    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
            for name in z.namelist():
                with z.open(name) as f:
                    raw = f.read()
                nl = name.lower()
                if nl.endswith(".hst"):
                    df = parse_hst(raw)
                elif nl.endswith(".csv"):
                    df = parse_csv(raw)
                else:
                    continue
                if df is not None and not df.empty:
                    frames.append(df)
    except Exception as e:
        print(f"    ZIP error: {e}")
        return None

    if not frames:
        return None
    result = pd.concat(frames).sort_index()
    return result[~result.index.duplicated(keep="first")]


# ── Ricampionamento M1 -> M5 ──────────────────────────────────────────────────

def m1_to_m5(df: pd.DataFrame) -> pd.DataFrame:
    return df.resample("5min").agg(
        Open  =("Open",  "first"),
        High  =("High",  "max"),
        Low   =("Low",   "min"),
        Close =("Close", "last"),
        Volume=("Volume","sum"),
    ).dropna(subset=["Open"])


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    session = requests.Session()
    print("Inizializzo sessione...")
    try:
        session.get("https://www.histdata.com/", headers=HEADERS, timeout=30)
    except Exception as e:
        print(f"  Homepage warning: {e}")

    for pair in PAIRS:
        print(f"\n{'='*52}\n  {pair}\n{'='*52}")
        all_years: list[pd.DataFrame] = []

        for year in YEARS:
            print(f"  [{pair} {year}] form...", end=" ", flush=True)

            form_data = get_form_data(session, pair, year)
            if not form_data:
                print("ERRORE: form non trovato – skip")
                time.sleep(3)
                continue

            fmt = form_data.get("platform", "?")
            print(f"OK ({fmt}), download...", end=" ", flush=True)

            zip_bytes = download_zip(session, pair, year, form_data)
            if not zip_bytes:
                time.sleep(3)
                continue

            df_m1 = zip_to_dataframe(zip_bytes)
            if df_m1 is None or df_m1.empty:
                print("dati vuoti – skip")
                time.sleep(2)
                continue

            df_m5 = m1_to_m5(df_m1)
            all_years.append(df_m5)
            print(f"OK  {len(df_m1):,} M1 -> {len(df_m5):,} M5")
            time.sleep(2)

        if not all_years:
            print(f"  Nessun dato per {pair}")
            continue

        full = pd.concat(all_years).sort_index()
        full = full[~full.index.duplicated(keep="first")]
        out  = os.path.join(OUTPUT, f"{pair}_M5_2020_2025.csv")
        full.to_csv(out)
        print(f"\n  Salvato: {out}")
        print(f"  {len(full):,} barre M5  |  {full.index[0]} -> {full.index[-1]}")


if __name__ == "__main__":
    main()
