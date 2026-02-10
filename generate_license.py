#!/usr/bin/env python3
"""Generatore di chiavi di licenza - SOLO PER IL VENDITORE.

NON distribuire questo file ai clienti!

Uso:
    python generate_license.py PRO cliente@email.com
    python generate_license.py PRO cliente@email.com --days 730
    python generate_license.py ENTERPRISE azienda@email.com --days 730
"""

import argparse
import sys
import time
from datetime import datetime

from bugbounty_scanner.license_manager import generate_license_key, verify_license_key, PLANS


def main():
    parser = argparse.ArgumentParser(
        description="Genera chiavi di licenza per Bug Bounty Scanner",
    )
    parser.add_argument("plan", choices=["LITE", "PRO", "ENTERPRISE"], help="Piano di licenza")
    parser.add_argument("email", help="Email del cliente")
    parser.add_argument("--days", type=int, default=365, help="Durata in giorni (default: 365)")

    args = parser.parse_args()

    print(f"\n  Generazione licenza {args.plan}")
    print(f"  Cliente: {args.email}")
    print(f"  Durata: {args.days} giorni")

    key = generate_license_key(args.plan, args.email, args.days)

    # Verifica che la chiave sia valida
    info = verify_license_key(key)
    expiry_date = datetime.fromtimestamp(info["expiry"]).strftime("%d/%m/%Y")

    print(f"\n  {'='*60}")
    print(f"  CHIAVE DI LICENZA GENERATA")
    print(f"  {'='*60}")
    print(f"\n  {key}\n")
    print(f"  Piano:    {info['plan']}")
    print(f"  Email:    {info['email']}")
    print(f"  Scadenza: {expiry_date}")
    print(f"  {'='*60}")
    print(f"\n  Invia questa chiave al cliente ({args.email}).")
    print(f"  Il cliente la attivera con:")
    print(f"    python -m bugbounty_scanner.activate {key}")
    print()


if __name__ == "__main__":
    main()
