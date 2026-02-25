#!/usr/bin/env python3
"""
HistData Downloader + M1->M5 Converter per iPhone (a-Shell)
============================================================
Scarica EURUSD e XAUUSD M1 da HistData e converte in M5.

INSTALLAZIONE (in a-Shell su iPhone):
    pip install requests beautifulsoup4 pandas

USO:
    python histdata_iphone.py

I file vengono salvati in ~/Documents/ (visibili nell'app File di iPhone)
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
YEARS  = range(2020, 2026)   # 2020 incluso → 2025 incluso
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

def get_token(session: requests.Session, pair: str, year: int, month: int) -> str | None:
    """Recupera il token CSRF dalla pagina di download HistData."""
    url = (
        f"https://www.histdata.com/download-free-forex-historical-data/"
        f"?/ascii/1-minute-bar-quotes/{pair}/{year}/{month}"
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


def download_zip(session: requests.Session, pair: str, year: int, month: int, token: str) -> bytes | None:
    """Scarica lo ZIP del mese da HistData."""
    ref = (
        f"https://www.histdata.com/download-free-forex-historical-data/"
        f"?/ascii/1-minute-bar-quotes/{pair}/{year}/{month}"
    )
    headers = {**HEADERS, "Referer": ref}
    data = {
        "tk":          token,
        "date":        f"{year}{month:02d}",
        "datemonth":   f"{year}{month:02d}",
        "platform":    "ASCII",
        "timeframe":   "M1",
        "fxpair":      pair,
    }
    try:
        r = session.post(
            "https://www.histdata.com/get.php",
            data=data, headers=headers, timeout=60
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
    """Estrae il CSV dallo ZIP e lo carica come DataFrame."""
    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
            csv_name = next((n for n in z.namelist() if n.endswith(".csv")), None)
            if not csv_name:
                print("    Nessun CSV nello ZIP")
                return None
            with z.open(csv_name) as f:
                df = pd.read_csv(
                    f, sep=";", header=None,
                    names=["Date", "Time", "Open", "High", "Low", "Close", "Volume"],
                    dtype={"Date": str, "Time": str}
                )
        df["DateTime"] = pd.to_datetime(df["Date"] + " " + df["Time"],
                                        format="%Y%m%d %H%M%S", errors="coerce")
        df = df.dropna(subset=["DateTime"]).set_index("DateTime")
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

        all_months: list[pd.DataFrame] = []

        for year in YEARS:
            for month in range(1, 13):
                label = f"{pair} {year}/{month:02d}"
                print(f"  Scarico {label} ...", end=" ", flush=True)

                token = get_token(session, pair, year, month)
                if not token:
                    print("token non trovato – skip")
                    time.sleep(1)
                    continue

                zip_bytes = download_zip(session, pair, year, month, token)
                if not zip_bytes:
                    time.sleep(2)
                    continue

                df_m1 = zip_to_dataframe(zip_bytes)
                if df_m1 is None or df_m1.empty:
                    print("CSV vuoto – skip")
                    time.sleep(1)
                    continue

                df_m5 = m1_to_m5(df_m1)
                all_months.append(df_m5)
                print(f"OK ({len(df_m5)} barre M5)")

                # Pausa educata per non far bloccare l'IP
                time.sleep(1.5)

        if not all_months:
            print(f"  Nessun dato scaricato per {pair}")
            continue

        # Unisci tutti i mesi e salva
        full = pd.concat(all_months).sort_index()
        full = full[~full.index.duplicated(keep="first")]

        out_path = os.path.join(OUTPUT, f"{pair}_M5_2020_2025.csv")
        full.to_csv(out_path)
        print(f"\n  Salvato: {out_path}")
        print(f"  Totale barre M5: {len(full):,}")
        print(f"  Da {full.index[0]}  a  {full.index[-1]}")


if __name__ == "__main__":
    main()
