"""
Converte i file M1 di HistData.com in M5.

HistData fornisce CSV con questo formato:
  20200102 170100;1.11234;1.11240;1.11220;1.11235;0

Utilizzo:
  python convert_histdata.py --input DAT_MT_EURUSD_M1_2020.csv --output EURUSD_M5.csv
  python convert_histdata.py --input_dir ./raw --symbol EURUSD --output EURUSD_M5.csv
"""

import argparse
import glob
import os
import pandas as pd


def load_histdata_csv(filepath: str) -> pd.DataFrame:
    """Carica un CSV di HistData e restituisce un DataFrame con indice datetime."""
    df = pd.read_csv(
        filepath,
        sep=";",
        header=None,
        names=["datetime", "open", "high", "low", "close", "volume"],
    )
    df["datetime"] = pd.to_datetime(df["datetime"], format="%Y%m%d %H%M%S")
    df.set_index("datetime", inplace=True)
    return df


def resample_to_m5(df: pd.DataFrame) -> pd.DataFrame:
    """Ricampiona dati M1 in M5."""
    df_m5 = df.resample("5min").agg(
        {
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum",
        }
    )
    df_m5.dropna(subset=["open"], inplace=True)
    return df_m5


def main():
    parser = argparse.ArgumentParser(description="Converti HistData M1 → M5")
    parser.add_argument("--input", help="Singolo file CSV M1 di HistData")
    parser.add_argument("--input_dir", help="Cartella con piu' file CSV M1")
    parser.add_argument("--symbol", default="EURUSD", help="Simbolo (per filtrare la cartella)")
    parser.add_argument("--output", required=True, help="File CSV M5 di output")
    args = parser.parse_args()

    files = []
    if args.input:
        files = [args.input]
    elif args.input_dir:
        pattern = os.path.join(args.input_dir, f"*{args.symbol}*M1*.csv")
        files = sorted(glob.glob(pattern))
        if not files:
            # prova senza filtro simbolo
            files = sorted(glob.glob(os.path.join(args.input_dir, "*.csv")))
    else:
        parser.error("Specifica --input o --input_dir")

    if not files:
        print("Nessun file trovato.")
        return

    print(f"File trovati: {len(files)}")
    dfs = []
    for f in files:
        print(f"  Carico: {os.path.basename(f)}")
        dfs.append(load_histdata_csv(f))

    df_all = pd.concat(dfs).sort_index()
    df_all = df_all[~df_all.index.duplicated(keep="first")]
    print(f"Righe M1 totali: {len(df_all)}")

    df_m5 = resample_to_m5(df_all)
    print(f"Righe M5 totali: {len(df_m5)}")

    df_m5.to_csv(args.output)
    size_mb = os.path.getsize(args.output) / 1_000_000
    print(f"Salvato: {args.output} ({size_mb:.1f} MB)")


if __name__ == "__main__":
    main()
