"""Gestione licenze - Generazione e verifica chiavi di licenza."""

import hashlib
import hmac
import json
import base64
import os
import sys
import time
from pathlib import Path

# Chiave segreta per firmare le licenze (HMAC-SHA256)
# IMPORTANTE: solo tu (Raffaele) conosci questa chiave.
# Senza di essa, nessuno puo generare chiavi valide.
_SECRET = b"RdV-BugBounty-Scanner-2025-K0braR@f91-SecretKey!"

# Piani disponibili e i loro permessi
PLANS = {
    "LITE": {
        "name": "LITE",
        "description": "Uso Personale - Solo modalita LITE",
        "allow_pro": False,
        "max_users": 1,
    },
    "PRO": {
        "name": "PRO",
        "description": "Uso Professionale - LITE + PRO (13 moduli)",
        "allow_pro": True,
        "max_users": 5,
    },
    "ENTERPRISE": {
        "name": "ENTERPRISE",
        "description": "Uso Aziendale - Tutte le funzionalita",
        "allow_pro": True,
        "max_users": -1,  # illimitati
    },
}

# Path dove viene salvata la licenza attivata
LICENSE_FILE = Path.home() / ".bbscanner_license"


def _sign(data: str) -> str:
    """Firma i dati con HMAC-SHA256."""
    return hmac.new(_SECRET, data.encode(), hashlib.sha256).hexdigest()


def generate_license_key(plan: str, email: str, days: int = 365) -> str:
    """Genera una chiave di licenza firmata.

    Args:
        plan: Piano (LITE, PRO, ENTERPRISE)
        email: Email del cliente
        days: Durata in giorni (default: 365)

    Returns:
        Chiave di licenza in formato BBSC-XXXX-XXXX-...
    """
    if plan not in PLANS:
        raise ValueError(f"Piano non valido: {plan}. Usa: {', '.join(PLANS.keys())}")

    expiry = int(time.time()) + (days * 86400)

    payload = json.dumps({
        "plan": plan,
        "email": email,
        "expiry": expiry,
        "created": int(time.time()),
    }, separators=(",", ":"))

    signature = _sign(payload)
    token = base64.urlsafe_b64encode(payload.encode()).decode()

    # Formato: BBSC-{base64_payload}-{signature_short}
    raw_key = f"{token}.{signature[:16]}.{signature[16:32]}.{signature[32:48]}.{signature[48:]}"

    # Formatta in blocchi leggibili: BBSC-XXXX-XXXX-...
    return f"BBSC-{raw_key}"


def verify_license_key(key: str) -> dict:
    """Verifica una chiave di licenza.

    Args:
        key: Chiave di licenza

    Returns:
        Dict con info licenza se valida

    Raises:
        LicenseError: Se la chiave non e valida
    """
    if not key or not key.startswith("BBSC-"):
        raise LicenseError("Formato chiave non valido.")

    try:
        raw = key[5:]  # Rimuovi "BBSC-"
        parts = raw.split(".")
        if len(parts) != 5:
            raise LicenseError("Chiave di licenza corrotta.")

        token = parts[0]
        signature = parts[1] + parts[2] + parts[3] + parts[4]

        payload = base64.urlsafe_b64decode(token).decode()

        # Verifica firma
        expected_sig = _sign(payload)
        if not hmac.compare_digest(signature, expected_sig):
            raise LicenseError("Chiave di licenza non valida (firma errata).")

        data = json.loads(payload)

        # Verifica scadenza
        if data["expiry"] < int(time.time()):
            days_ago = (int(time.time()) - data["expiry"]) // 86400
            raise LicenseError(
                f"Licenza scaduta da {days_ago} giorni. "
                f"Contatta devita.raffaele@gmail.com per il rinnovo."
            )

        # Verifica piano
        plan = data.get("plan")
        if plan not in PLANS:
            raise LicenseError("Piano non riconosciuto.")

        return {
            "valid": True,
            "plan": plan,
            "email": data["email"],
            "expiry": data["expiry"],
            "plan_info": PLANS[plan],
        }

    except (json.JSONDecodeError, KeyError, ValueError) as e:
        raise LicenseError(f"Chiave di licenza corrotta: {e}")


def activate_license(key: str) -> dict:
    """Attiva una licenza salvandola nel sistema.

    Args:
        key: Chiave di licenza

    Returns:
        Dict con info licenza
    """
    info = verify_license_key(key)
    LICENSE_FILE.write_text(key.strip())
    return info


def get_active_license() -> dict:
    """Legge e verifica la licenza attiva dal file di configurazione.

    Returns:
        Dict con info licenza se attiva e valida, None altrimenti
    """
    if not LICENSE_FILE.exists():
        return None

    key = LICENSE_FILE.read_text().strip()
    if not key:
        return None

    try:
        return verify_license_key(key)
    except LicenseError:
        return None


def check_license(require_pro=False) -> dict:
    """Controlla che ci sia una licenza valida, altrimenti esce.

    Questa funzione viene chiamata all'avvio del CLI.
    Se non c'e licenza valida, stampa un messaggio e termina.

    Args:
        require_pro: Se True, richiede piano PRO o ENTERPRISE

    Returns:
        Dict con info licenza
    """
    # 1. Controlla variabile d'ambiente
    env_key = os.environ.get("BBSCANNER_LICENSE")
    if env_key:
        try:
            info = verify_license_key(env_key)
            if require_pro and not info["plan_info"]["allow_pro"]:
                print("\n  ERRORE LICENZA: La modalita PRO richiede una licenza PRO o ENTERPRISE.")
                print("  La tua licenza LITE non include questa funzionalita.")
                print("  Contatta devita.raffaele@gmail.com per l'upgrade.\n")
                sys.exit(1)
            return info
        except LicenseError as e:
            print(f"\n  ERRORE LICENZA: {e}\n")
            sys.exit(1)

    # 2. Controlla file licenza
    info = get_active_license()
    if info:
        if require_pro and not info["plan_info"]["allow_pro"]:
            print("\n  ERRORE LICENZA: La modalita PRO richiede una licenza PRO o ENTERPRISE.")
            print("  La tua licenza LITE non include questa funzionalita.")
            print(f"  Piano attuale: {info['plan']}")
            print("  Contatta devita.raffaele@gmail.com per l'upgrade.\n")
            sys.exit(1)
        return info

    # 3. Nessuna licenza trovata
    print("""
  ============================================================
   LICENZA RICHIESTA
  ============================================================

   Questo software richiede una licenza valida per funzionare.

   Non hai ancora una licenza? Acquistala:
     Email: devita.raffaele@gmail.com

   Piani disponibili:
     LITE       - Uso personale (solo modalita LITE)
     PRO        - Uso professionale (LITE + PRO, 13 moduli)
     ENTERPRISE - Uso aziendale (tutto + supporto prioritario)

   Hai gia una chiave? Attivala con:
     python -m bugbounty_scanner.activate BBSC-LA-TUA-CHIAVE

   Oppure imposta la variabile d'ambiente:
     export BBSCANNER_LICENSE="BBSC-LA-TUA-CHIAVE"

  ============================================================
""")
    sys.exit(1)


class LicenseError(Exception):
    """Errore di licenza."""
    pass
