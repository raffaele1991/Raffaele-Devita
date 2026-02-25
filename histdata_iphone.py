#!/usr/bin/env python3
"""
HistData Downloader + M1->M5 Converter per iPhone (a-Shell)
============================================================
Scarica EURUSD e XAUUSD M1 da HistData (1 ZIP per anno) e converte in M5.
Totale: 12 ZIP  (2 coppie x 6 anni)

INSTALLAZIONE (in a-Shell su iPhone):
    pip install requests beautifulsoup4 pandas

USO:
    python histdata_iphone.py

I file vengono salvati in ~/Documents/HistData_M5/ (visibili nell'app File)
"""

import requests
from bs4 import BeautifulSoup
import zipfile
import pandas as pd
import io
import os
import time

# ── Configurazione ────────────────────────────────────────────────────────────
PAIRS  = ["EURUSD", "XAUUSD"]
YEARS  = range(2020, 2026)   # 2020 → 2025 inclusi
OUTPUT = os.path.expanduser("~/Documents/HistData_M5")
os.makedirs(OUTPUT, exist_ok=True)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# ── Funzioni ──────────────────────────────────────────────────────────────────

def get_token(session: requests.Session, pair: str, year: int) -> str | None:
    """Recupera il token CSRF dalla pagina di download annuale HistData."""
    url = (
        f"https://www.histdata.com/download-free-forex-historical-data/"
        f"?/ascii/1-minute-bar-quotes/{pair}/{year}"
    )
    try:
        r = session.get(url, headers=HEADERS, timeout=30)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        inp = soup.find("input", {"id": "tk"})
        return inp["value"] if inp else None
    except Exception as e:
        print(f"    Errore pagina token: {e}")
        return None


def download_zip(session: requests.Session, pair: str, year: int, token: str) -> bytes | None:
    """Scarica lo ZIP annuale da HistData (datemonth=0 = anno intero)."""
    ref = (
        f"https://www.histdata.com/download-free-forex-historical-data/"
        f"?/ascii/1-minute-bar-quotes/{pair}/{year}"
    )
    headers = {**HEADERS, "Referer": ref}
    data = {
        "tk":          token,
        "date":        str(year),
        "datemonth":   "0",        # 0 = anno intero
        "platform":    "ASCII",
        "timeframe":   "M1",
        "fxpair":      pair,
    }
    try:
        r = session.post(
            "https://www.histdata.com/get.php",
            data=data, headers=headers, timeout=120
        )
        r.raise_for_status()
        if len(r.content) < 1000:
            print(f"    Risposta troppo piccola ({len(r.content)} bytes) – skip")
            return None
        return r.content
    except Exception as e:
        print(f"    Errore download: {e}")
        return None


def zip_to_dataframe(zip_bytes: bytes) -> pd.DataFrame | None:
    """Estrae tutti i CSV dallo ZIP annuale e li unisce in un DataFrame."""
    try:
        frames = []
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
            csv_names = [n for n in z.namelist() if n.endswith(".csv")]
            if not csv_names:
                print("    Nessun CSV nello ZIP")
                return None
            for csv_name in csv_names:
                with z.open(csv_name) as f:
                    df = pd.read_csv(
                        f, sep=";", header=None,
                        names=["Date", "Time", "Open", "High", "Low", "Close", "Volume"],
                        dtype={"Date": str, "Time": str}
                    )
                frames.append(df)

        df = pd.concat(frames, ignore_index=True)
        df["DateTime"] = pd.to_datetime(
            df["Date"] + " " + df["Time"],
            format="%Y%m%d %H%M%S", errors="coerce"
        )
        df = df.dropna(subset=["DateTime"]).set_index("DateTime").sort_index()
        for col in ["Open", "High", "Low", "Close", "Volume"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        return df.dropna()
    except Exception as e:
        print(f"    Errore parsing ZIP: {e}")
        return None


def m1_to_m5(df: pd.DataFrame) -> pd.DataFrame:
    """Ricampiona M1 → M5 (OHLCV)."""
    return df.resample("5min").agg(
        Open=("Open", "first"),
        High=("High", "max"),
        Low=("Low", "min"),
        Close=("Close", "last"),
        Volume=("Volume", "sum"),
    ).dropna(subset=["Open"])


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    session = requests.Session()

    for pair in PAIRS:
        print(f"\n{'='*50}")
        print(f"  {pair}")
        print(f"{'='*50}")

        all_years: list[pd.DataFrame] = []

        for year in YEARS:
            print(f"  Scarico {pair} {year} ...", end=" ", flush=True)

            token = get_token(session, pair, year)
            if not token:
                print("token non trovato – skip")
                time.sleep(2)
                continue

            zip_bytes = download_zip(session, pair, year, token)
            if not zip_bytes:
                time.sleep(3)
                continue

            df_m1 = zip_to_dataframe(zip_bytes)
            if df_m1 is None or df_m1.empty:
                print("CSV vuoto – skip")
                time.sleep(1)
                continue

            df_m5 = m1_to_m5(df_m1)
            all_years.append(df_m5)
            print(f"OK  {len(df_m1):,} barre M1  →  {len(df_m5):,} barre M5")

            time.sleep(2)   # pausa educata tra un anno e l'altro

        if not all_years:
            print(f"  Nessun dato scaricato per {pair}")
            continue

        full = pd.concat(all_years).sort_index()
        full = full[~full.index.duplicated(keep="first")]

        out_path = os.path.join(OUTPUT, f"{pair}_M5_2020_2025.csv")
        full.to_csv(out_path)
        print(f"\n  Salvato: {out_path}")
        print(f"  Totale barre M5: {len(full):,}")
        print(f"  Da {full.index[0]}  a  {full.index[-1]}")


if __name__ == "__main__":
    main()
