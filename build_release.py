#!/usr/bin/env python3
"""Script per creare il pacchetto distribuibile del Bug Bounty Scanner.

Compila il software in un eseguibile binario con PyInstaller.
Il cliente riceve UN SOLO FILE eseguibile, senza codice sorgente.

Uso:
    pip install pyinstaller
    python build_release.py

Genera:
    dist/bbscanner         - Eseguibile modalita LITE
    dist/bbscanner_pro     - Eseguibile modalita PRO
    dist/bbscanner_activate - Eseguibile per attivare la licenza

Cosa inviare al cliente:
    1. I 3 file eseguibili dalla cartella dist/
    2. La chiave di licenza generata con generate_license.py
    3. Il file README_CLIENTE.md (generato automaticamente)
"""

import os
import subprocess
import sys
import shutil


def check_pyinstaller():
    """Verifica che PyInstaller sia installato."""
    try:
        import PyInstaller
        print(f"  PyInstaller {PyInstaller.__version__} trovato")
        return True
    except ImportError:
        print("  ERRORE: PyInstaller non installato.")
        print("  Installalo con: pip install pyinstaller")
        return False


def build_executable(script, name, hidden_imports=None):
    """Compila uno script Python in un eseguibile."""
    print(f"\n  Compilazione {name}...")

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",           # Un solo file eseguibile
        "--clean",             # Pulisci cache
        "--name", name,        # Nome dell'eseguibile
        "--noconfirm",         # Sovrascrivi senza chiedere
    ]

    # Importa tutti i moduli del pacchetto
    if hidden_imports:
        for imp in hidden_imports:
            cmd.extend(["--hidden-import", imp])

    cmd.append(script)

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  ERRORE compilazione {name}:")
        print(result.stderr[-500:] if len(result.stderr) > 500 else result.stderr)
        return False

    print(f"  {name} compilato con successo!")
    return True


def generate_client_readme():
    """Genera un README semplificato per il cliente."""
    readme = """# Bug Bounty Vulnerability Scanner Agent v2.0

## Installazione

### 1. Attiva la licenza
```bash
./bbscanner_activate BBSC-LA-TUA-CHIAVE
```

### 2. Usa lo scanner

Modalita LITE:
```bash
./bbscanner -t example.com
```

Modalita PRO:
```bash
./bbscanner_pro -t example.com
```

### 3. Verifica stato licenza
```bash
./bbscanner_activate
```

## Comandi rapidi

```bash
# Scansione completa LITE
./bbscanner -t example.com

# Scansione completa PRO
./bbscanner_pro -t example.com

# PRO con scope automatico da HackerOne
./bbscanner_pro -t example.com --program "https://hackerone.com/example"

# PRO con notifiche Telegram
./bbscanner_pro -t example.com --telegram-token "TOKEN" --telegram-chat "CHAT_ID"

# PRO solo Nuclei e Nmap
./bbscanner_pro -t example.com --pipeline nuclei nmap
```

## Supporto

Per problemi, rinnovi o upgrade: **devita.raffaele@gmail.com**

## Licenza

Questo software e protetto da licenza commerciale.
La chiave di licenza e personale e non trasferibile.
Vedi il file LICENSE per i termini completi.
"""

    with open("dist/README_CLIENTE.md", "w") as f:
        f.write(readme)
    print("  README_CLIENTE.md generato")


def copy_license():
    """Copia il file LICENSE nella cartella dist."""
    if os.path.exists("LICENSE"):
        shutil.copy("LICENSE", "dist/LICENSE")
        print("  LICENSE copiato")


def main():
    print("\n  ================================================")
    print("  BUILD RELEASE - Bug Bounty Scanner")
    print("  ================================================\n")

    if not check_pyinstaller():
        sys.exit(1)

    # Moduli da includere nell'eseguibile
    hidden = [
        "bugbounty_scanner",
        "bugbounty_scanner.license_manager",
        "bugbounty_scanner.scanner",
        "bugbounty_scanner.orchestrator",
        "bugbounty_scanner.reporter",
        "bugbounty_scanner.http_session",
        "bugbounty_scanner.program_parser",
        "bugbounty_scanner.scope_checker",
        "bugbounty_scanner.notifier",
        "bugbounty_scanner.config",
        "bugbounty_scanner.modules",
        "bugbounty_scanner.modules.recon",
        "bugbounty_scanner.modules.headers",
        "bugbounty_scanner.modules.xss",
        "bugbounty_scanner.modules.sqli",
        "bugbounty_scanner.modules.ssrf",
        "bugbounty_scanner.modules.open_redirect",
        "bugbounty_scanner.modules.sensitive_files",
        "bugbounty_scanner.modules.crawler",
        "bugbounty_scanner.modules.wayback",
        "bugbounty_scanner.modules.js_scanner",
        "bugbounty_scanner.tools",
        "bugbounty_scanner.tools.base",
        "bugbounty_scanner.tools.subfinder",
        "bugbounty_scanner.tools.httpx_tool",
        "bugbounty_scanner.tools.nmap_tool",
        "bugbounty_scanner.tools.nuclei_tool",
        "bugbounty_scanner.tools.ffuf_tool",
        "bugbounty_scanner.tools.sqlmap_tool",
        "bugbounty_scanner.tools.dalfox_tool",
        "bugbounty_scanner.tools.nikto_tool",
    ]

    # Compila i 3 eseguibili
    ok = True
    ok = build_executable("bugbounty_scanner/cli.py", "bbscanner", hidden) and ok
    ok = build_executable("bugbounty_scanner/cli_pro.py", "bbscanner_pro", hidden) and ok
    ok = build_executable("bugbounty_scanner/activate.py", "bbscanner_activate", hidden) and ok

    if not ok:
        print("\n  ERRORE: Alcune compilazioni sono fallite.")
        sys.exit(1)

    # Genera file per il cliente
    generate_client_readme()
    copy_license()

    # Pulizia file temporanei PyInstaller
    for d in ["build", "*.spec"]:
        if os.path.isdir(d):
            shutil.rmtree(d, ignore_errors=True)
    for f in os.listdir("."):
        if f.endswith(".spec"):
            os.remove(f)

    print(f"\n  ================================================")
    print(f"  BUILD COMPLETATA!")
    print(f"  ================================================")
    print(f"\n  File pronti in: dist/")
    print(f"    - bbscanner           (modalita LITE)")
    print(f"    - bbscanner_pro       (modalita PRO)")
    print(f"    - bbscanner_activate  (attivazione licenza)")
    print(f"    - README_CLIENTE.md   (istruzioni per il cliente)")
    print(f"    - LICENSE             (contratto di licenza)")
    print(f"\n  Invia la cartella dist/ al cliente dopo il pagamento.")
    print(f"  NON inviare mai il codice sorgente!\n")


if __name__ == "__main__":
    main()
