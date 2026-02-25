#!/usr/bin/env python3
"""
Merge Volume 30M → 5M
=====================
Prende i CSV da 30m esportati da MT5 (con tickvol) e li unisce ai CSV M5
già esistenti che non hanno volume reale (volume=0).

Per ogni barra da 30m: assegna volume/6 alle 6 barre da 5m corrispondenti.

USO:
    python merge_volume_30m.py --vol30  XAUUSD_M30_2020_2023.csv XAUUSD_M30_2024.csv
                               --m5     trading_system/data/XAUUSD_M5.csv
                               --out    trading_system/data/XAUUSD_M5.csv

    --vol30  uno o più CSV da 30m con tickvol (MT5 export)
    --m5     CSV da 5m senza volume (output di m1_to_m5_pc.py / histdata)
    --out    percorso output (può sovrascrivere --m5)

Formati MT5 accettati (rilevati automaticamente):
    <DATE>\t<TIME>\t<OPEN>\t<HIGH>\t<LOW>\t<CLOSE>\t<TICKVOL>\t<VOL>\t<SPREAD>
    <DATE>\t<TIME>\t<OPEN>\t<HIGH>\t<LOW>\t<CLOSE>\t<TICKVOL>
    datetime,open,high,low,close,volume  (già normalizzato)
"""

import argparse
import sys
from pathlib import Path

import pandas as pd


# ─── Parsing ─────────────────────────────────────────────────────────────────

def _parse_mt5(path: str) -> pd.DataFrame:
    """Legge un CSV MT5 in qualunque formato ragionevole."""
    p = Path(path)
    raw = p.read_text(encoding="utf-8", errors="replace")
    first = raw.lstrip().split("\n")[0]

    # Formato tab-separated (export standard MT5)
    if "\t" in first:
        df = pd.read_csv(path, sep="\t")
        df.columns = [c.strip("<>").lower() for c in df.columns]

        # Combina DATE e TIME se separati
        if "date" in df.columns and "time" in df.columns:
            df["datetime"] = pd.to_datetime(
                df["date"].astype(str) + " " + df["time"].astype(str)
            )
            df = df.drop(columns=["date", "time"])
        elif "datetime" not in df.columns:
            raise ValueError(f"Colonna datetime non trovata in {path}")

        # Rinomina tickvol → volume (MT5 esporta 'tickvol' per default)
        for candidate in ("tickvol", "tick vol", "tick_vol"):
            if candidate in df.columns:
                df = df.rename(columns={candidate: "volume"})
                break

    # Formato CSV con virgola (già normalizzato)
    else:
        df = pd.read_csv(path)
        df.columns = [c.strip().lower() for c in df.columns]
        if "datetime" not in df.columns:
            # prova col 0 come datetime
            df = df.rename(columns={df.columns[0]: "datetime"})
        df["datetime"] = pd.to_datetime(df["datetime"])

    df["datetime"] = pd.to_datetime(df["datetime"])
    df = df.sort_values("datetime").reset_index(drop=True)

    if "volume" not in df.columns:
        raise ValueError(f"Colonna volume/tickvol non trovata in {path}")

    return df[["datetime", "volume"]]


def load_volume_30m(paths: list[str]) -> pd.DataFrame:
    """Carica e concatena più CSV da 30m → DataFrame con datetime e volume."""
    frames = []
    for p in paths:
        print(f"  Carico 30m: {p}")
        frames.append(_parse_mt5(p))
    vol = pd.concat(frames).drop_duplicates("datetime").sort_values("datetime")
    vol = vol.reset_index(drop=True)
    print(f"  Barre 30m totali: {len(vol):,}  |  da {vol.datetime.min()} a {vol.datetime.max()}")
    return vol


def load_m5(path: str) -> pd.DataFrame:
    """Carica il CSV M5 principale."""
    print(f"  Carico M5: {path}")
    df = pd.read_csv(path)
    df.columns = [c.strip().lower() for c in df.columns]
    if "datetime" not in df.columns:
        df = df.rename(columns={df.columns[0]: "datetime"})
    df["datetime"] = pd.to_datetime(df["datetime"])
    df = df.sort_values("datetime").reset_index(drop=True)
    if "volume" not in df.columns:
        df["volume"] = 0
    print(f"  Barre M5 totali:  {len(df):,}  |  da {df.datetime.min()} a {df.datetime.max()}")
    return df


# ─── Espansione 30m → 5m ─────────────────────────────────────────────────────

def expand_30m_to_5m(vol30: pd.DataFrame) -> pd.DataFrame:
    """
    Crea un DataFrame indexed sui 5m con volume = vol_30m / 6.
    Ogni barra 30m (timestamp = apertura) genera 6 barre a +0,+5,+10,+15,+20,+25 min.
    """
    rows = []
    for _, row in vol30.iterrows():
        base = row["datetime"]
        v6 = row["volume"] / 6.0
        for offset in range(0, 30, 5):
            rows.append({"datetime": base + pd.Timedelta(minutes=offset), "volume_30": v6})
    df5 = pd.DataFrame(rows)
    df5 = df5.drop_duplicates("datetime").sort_values("datetime").reset_index(drop=True)
    return df5


# ─── Merge ───────────────────────────────────────────────────────────────────

def merge(m5: pd.DataFrame, vol5: pd.DataFrame) -> pd.DataFrame:
    """
    Aggiunge volume_30 alle barre M5.
    - Se la barra M5 ha già volume > 0 (tickvol MT5 diretto), lo mantiene.
    - Altrimenti usa volume_30 (derivato da 30m).
    """
    merged = m5.merge(vol5, on="datetime", how="left")

    # volume_30 NaN → 0 (barre fuori range dei 30m)
    merged["volume_30"] = merged["volume_30"].fillna(0)

    # Usa il tickvol diretto dove disponibile, altrimenti il proxy da 30m
    has_direct = merged["volume"] > 0
    merged.loc[~has_direct, "volume"] = merged.loc[~has_direct, "volume_30"]
    merged = merged.drop(columns=["volume_30"])

    filled = (merged["volume"] > 0).sum()
    total = len(merged)
    print(f"\n  Barre con volume: {filled:,}/{total:,} ({filled/total*100:.1f}%)")
    return merged


# ─── Main ────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description="Merge tickvol 30m → M5")
    ap.add_argument("--vol30", nargs="+", required=True,
                    help="Uno o più CSV da 30m con tickvol (MT5 export)")
    ap.add_argument("--m5", required=True,
                    help="CSV M5 esistente (OHLCV, volume può essere 0)")
    ap.add_argument("--out", default=None,
                    help="Output path (default: sovrascrive --m5)")
    args = ap.parse_args()

    out_path = args.out or args.m5

    print("\n[1/4] Carico i CSV 30m con volume...")
    vol30 = load_volume_30m(args.vol30)

    print("\n[2/4] Carico M5...")
    m5 = load_m5(args.m5)

    print("\n[3/4] Espando 30m → 5m (volume/6 per barra)...")
    vol5 = expand_30m_to_5m(vol30)
    print(f"  Barre 5m generate: {len(vol5):,}")

    print("\n[4/4] Merge e salvataggio...")
    result = merge(m5, vol5)
    result.to_csv(out_path, index=False)
    print(f"  Salvato: {out_path}  ({len(result):,} barre)")

    # Statistiche volume
    v = result["volume"]
    print(f"\n  Volume medio (barre non-zero): {v[v>0].mean():.1f}")
    print(f"  Volume max:                    {v.max():.0f}")
    print("\nFatto.")


if __name__ == "__main__":
    main()
