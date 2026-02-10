#!/usr/bin/env python3
"""Script per creare il pacchetto distribuibile del Bug Bounty Scanner.

Crea un archivio ZIP pronto da inviare al cliente con:
  - Codice compilato in bytecode (.pyc) - non leggibile come il sorgente
  - Script di avvio semplici (bbscanner, bbscanner_pro, bbscanner_activate)
  - README e LICENSE per il cliente

Uso:
    python build_release.py

Genera:
    dist/bugbounty_scanner_v2.0.zip  - Archivio pronto da inviare al cliente
"""

import compileall
import os
import py_compile
import shutil
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).parent
DIST_DIR = PROJECT_DIR / "dist"
BUILD_DIR = PROJECT_DIR / "build" / "release"


def clean():
    """Pulisci le cartelle di build."""
    if BUILD_DIR.exists():
        shutil.rmtree(BUILD_DIR)
    DIST_DIR.mkdir(exist_ok=True)
    BUILD_DIR.mkdir(parents=True)


def compile_package():
    """Compila tutto il pacchetto in bytecode .pyc."""
    print("  [1/4] Compilazione bytecode...")

    src = PROJECT_DIR / "bugbounty_scanner"
    dst = BUILD_DIR / "bugbounty_scanner"

    # Copia la struttura
    shutil.copytree(src, dst)

    # Compila tutti i .py in .pyc
    compileall.compile_dir(str(dst), quiet=1, force=True)

    # Rimuovi i file .py sorgente, tieni solo i .pyc
    count = 0
    for pyc_file in dst.rglob("*.pyc"):
        # Sposta .pyc dalla cartella __pycache__ alla cartella del modulo
        module_dir = pyc_file.parent.parent
        # Nome originale: modulo.cpython-XY.pyc -> modulo.pyc
        original_name = pyc_file.stem.split(".")[0] + ".pyc"
        dest = module_dir / original_name
        shutil.move(str(pyc_file), str(dest))
        count += 1

    # Rimuovi le cartelle __pycache__ e i file .py
    for pycache in dst.rglob("__pycache__"):
        shutil.rmtree(pycache)
    for py_file in dst.rglob("*.py"):
        py_file.unlink()

    print(f"         {count} moduli compilati")


def create_launchers():
    """Crea gli script di avvio per il cliente."""
    print("  [2/4] Creazione script di avvio...")

    # Script LITE
    (BUILD_DIR / "bbscanner").write_text(
        '#!/usr/bin/env python3\n'
        'import sys, os\n'
        'sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))\n'
        'from bugbounty_scanner.cli import main\n'
        'main()\n'
    )

    # Script PRO
    (BUILD_DIR / "bbscanner_pro").write_text(
        '#!/usr/bin/env python3\n'
        'import sys, os\n'
        'sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))\n'
        'from bugbounty_scanner.cli_pro import main\n'
        'main()\n'
    )

    # Script attivazione
    (BUILD_DIR / "bbscanner_activate").write_text(
        '#!/usr/bin/env python3\n'
        'import sys, os\n'
        'sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))\n'
        'from bugbounty_scanner.activate import main\n'
        'main()\n'
    )

    # Rendi eseguibili
    for script in ["bbscanner", "bbscanner_pro", "bbscanner_activate"]:
        os.chmod(BUILD_DIR / script, 0o755)


def create_client_files():
    """Crea README e copia LICENSE per il cliente."""
    print("  [3/4] Creazione documentazione cliente...")

    # README per il cliente
    (BUILD_DIR / "README.md").write_text("""# Bug Bounty Vulnerability Scanner Agent v2.0

## Requisiti
- Python 3.8 o superiore
- pip install requests beautifulsoup4 dnspython Jinja2 urllib3

## Installazione

### 1. Estrai i file
Estrai questo archivio in una cartella a tua scelta.

### 2. Installa le dipendenze Python
```bash
pip install requests beautifulsoup4 dnspython Jinja2 urllib3
```

### 3. Attiva la licenza
```bash
python3 bbscanner_activate BBSC-LA-TUA-CHIAVE
```

### 4. Usa lo scanner
```bash
# Modalita LITE
python3 bbscanner -t example.com

# Modalita PRO
python3 bbscanner_pro -t example.com
```

### 5. Verifica stato licenza
```bash
python3 bbscanner_activate
```

## Comandi utili

```bash
# Scansione completa PRO
python3 bbscanner_pro -t example.com

# Con scope automatico da HackerOne
python3 bbscanner_pro -t example.com --program "https://hackerone.com/example"

# Con notifiche Telegram
python3 bbscanner_pro -t example.com --telegram-token "TOKEN" --telegram-chat "CHAT_ID"

# Solo Nuclei e Nmap
python3 bbscanner_pro -t example.com --pipeline nuclei nmap
```

## Supporto
Per problemi, rinnovi o upgrade: devita.raffaele@gmail.com

## Licenza
Software protetto da licenza commerciale. Chiave personale e non trasferibile.
""")

    # Copia LICENSE
    license_file = PROJECT_DIR / "LICENSE"
    if license_file.exists():
        shutil.copy(license_file, BUILD_DIR / "LICENSE")

    # Copia requirements.txt
    req_file = PROJECT_DIR / "requirements.txt"
    if req_file.exists():
        shutil.copy(req_file, BUILD_DIR / "requirements.txt")

    # Copia install_tools.sh per la modalita PRO
    tools_file = PROJECT_DIR / "install_tools.sh"
    if tools_file.exists():
        shutil.copy(tools_file, BUILD_DIR / "install_tools.sh")
        os.chmod(BUILD_DIR / "install_tools.sh", 0o755)


def create_zip():
    """Crea l'archivio ZIP finale."""
    print("  [4/4] Creazione archivio ZIP...")

    zip_name = "bugbounty_scanner_v2.0"
    zip_path = DIST_DIR / zip_name

    shutil.make_archive(str(zip_path), "zip", str(BUILD_DIR))

    final_path = DIST_DIR / f"{zip_name}.zip"
    size_mb = final_path.stat().st_size / (1024 * 1024)

    print(f"         {final_path} ({size_mb:.1f} MB)")
    return final_path


def main():
    print("\n  ================================================")
    print("  BUILD RELEASE - Bug Bounty Scanner v2.0")
    print("  ================================================\n")

    clean()
    compile_package()
    create_launchers()
    create_client_files()
    zip_path = create_zip()

    # Pulizia build temporanei
    shutil.rmtree(BUILD_DIR.parent, ignore_errors=True)

    print(f"\n  ================================================")
    print(f"  BUILD COMPLETATA!")
    print(f"  ================================================")
    print(f"\n  File pronto da inviare al cliente:")
    print(f"    {zip_path}")
    print(f"\n  Il cliente riceve:")
    print(f"    - Codice compilato (bytecode, non leggibile)")
    print(f"    - Script di avvio (bbscanner, bbscanner_pro, bbscanner_activate)")
    print(f"    - README con istruzioni")
    print(f"    - LICENSE")
    print(f"    - requirements.txt")
    print(f"\n  COME INVIARE:")
    print(f"    1. Genera la chiave: python generate_license.py PRO email@cliente.com")
    print(f"    2. Manda il file ZIP + la chiave via email al cliente")
    print(f"  ================================================\n")


if __name__ == "__main__":
    main()
