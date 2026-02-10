#!/usr/bin/env python3
"""Attivazione licenza Bug Bounty Scanner.

Uso:
    python -m bugbounty_scanner.activate BBSC-LA-TUA-CHIAVE
"""

import sys
from datetime import datetime

from bugbounty_scanner.license_manager import (
    activate_license,
    get_active_license,
    LicenseError,
    LICENSE_FILE,
)


def main():
    if len(sys.argv) < 2:
        # Mostra stato licenza corrente
        info = get_active_license()
        if info:
            expiry_date = datetime.fromtimestamp(info["expiry"]).strftime("%d/%m/%Y")
            days_left = (info["expiry"] - int(__import__("time").time())) // 86400
            print(f"\n  Licenza attiva")
            print(f"  Piano:      {info['plan']} - {info['plan_info']['description']}")
            print(f"  Email:      {info['email']}")
            print(f"  Scadenza:   {expiry_date} ({days_left} giorni rimasti)")
            print(f"  File:       {LICENSE_FILE}\n")
        else:
            print("\n  Nessuna licenza attiva.")
            print("  Per attivare: python -m bugbounty_scanner.activate BBSC-LA-TUA-CHIAVE")
            print("  Per acquistare: devita.raffaele@gmail.com\n")
        return

    key = sys.argv[1].strip()

    try:
        info = activate_license(key)
        expiry_date = datetime.fromtimestamp(info["expiry"]).strftime("%d/%m/%Y")
        days_left = (info["expiry"] - int(__import__("time").time())) // 86400

        print(f"""
  ============================================================
   LICENZA ATTIVATA CON SUCCESSO!
  ============================================================

   Piano:      {info['plan']} - {info['plan_info']['description']}
   Email:      {info['email']}
   Scadenza:   {expiry_date} ({days_left} giorni rimasti)
   Salvata in: {LICENSE_FILE}

   Ora puoi usare lo scanner:
     python -m bugbounty_scanner.cli -t example.com
{"     python -m bugbounty_scanner.cli_pro -t example.com" if info['plan_info']['allow_pro'] else ""}
  ============================================================
""")
    except LicenseError as e:
        print(f"\n  ERRORE: {e}")
        print("  Verifica la chiave e riprova.")
        print("  Supporto: devita.raffaele@gmail.com\n")
        sys.exit(1)


if __name__ == "__main__":
    main()
