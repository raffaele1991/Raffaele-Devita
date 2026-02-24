"""
Avvio Dashboard – SMC+ML Trading Bot
======================================
Esegui con:
    python run_dashboard.py          → porta default 5050
    python run_dashboard.py --port 8080

La dashboard si apre nel browser su http://localhost:5050
Il bot gira separatamente con:  python trading_system/bot.py
"""

import argparse
import webbrowser
import threading
import time
import os
import sys

# Aggiungi il root al path
ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

from trading_system.dashboard.app import app


def open_browser(port: int):
    """Apre il browser dopo un breve ritardo (aspetta che Flask si avvii)."""
    time.sleep(1.2)
    webbrowser.open(f"http://localhost:{port}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Dashboard Trading Bot")
    parser.add_argument("--port", type=int, default=5050, help="Porta HTTP (default: 5050)")
    parser.add_argument("--no-browser", action="store_true", help="Non aprire il browser automaticamente")
    args = parser.parse_args()

    port = int(os.environ.get("DASHBOARD_PORT", args.port))

    print()
    print("  ╔══════════════════════════════════════════╗")
    print("  ║     SMC+ML Trading Bot – Dashboard       ║")
    print(f"  ║     http://localhost:{port}               ║")
    print("  ║     Ctrl+C per fermare                   ║")
    print("  ╚══════════════════════════════════════════╝")
    print()

    if not args.no_browser:
        t = threading.Thread(target=open_browser, args=(port,), daemon=True)
        t.start()

    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
