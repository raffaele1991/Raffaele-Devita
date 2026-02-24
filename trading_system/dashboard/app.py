"""
Dashboard – SMC+ML Trading Bot
================================
Server Flask locale che espone la dashboard web e le API di stato.

Avvio:
    python run_dashboard.py
    oppure
    python -m trading_system.dashboard.app

API:
    GET  /           → dashboard HTML
    GET  /api/state  → stato corrente del bot (JSON)
    GET  /api/log    → ultime N righe di log (JSON)
    POST /api/control → {"action": "stop"|"start"} per controllare il bot
"""

import os
import json
from pathlib import Path
from flask import Flask, jsonify, render_template, request

# ─── PATH ─────────────────────────────────────────────────────────────────────

ROOT        = Path(__file__).parent.parent.parent          # repo root
STATE_FILE  = ROOT / "trading_system" / "state.json"
CONTROL_FILE = ROOT / "trading_system" / "control.json"
LOG_FILE    = ROOT / "trading_system" / "trading.log"

# ─── APP ──────────────────────────────────────────────────────────────────────

app = Flask(__name__, template_folder="templates")


def _default_state() -> dict:
    """Stato vuoto mostrato quando il bot non ha ancora scritto state.json."""
    return {
        "bot_status":          "offline",
        "timestamp":           None,
        "session":             "CLOSED",
        "minutes_to_next":     None,
        "balance":             0.0,
        "daily_dd_pct":        0.0,
        "total_dd_pct":        0.0,
        "trades_today":        0,
        "win_rate":            0.0,
        "consecutive_losses":  0,
        "open_positions":      0,
        "total_wins":          0,
        "total_losses":        0,
        "symbols":             {},
        "open_trades":         [],
        "closed_trades":       [],
    }


# ─── ROUTES ───────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/state")
def api_state():
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                state = json.load(f)
            return jsonify(state)
        except (json.JSONDecodeError, OSError):
            pass
    return jsonify(_default_state())


@app.route("/api/log")
def api_log():
    n = int(request.args.get("lines", 80))
    lines = []
    if LOG_FILE.exists():
        try:
            with open(LOG_FILE, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
            lines = [l.rstrip() for l in lines[-n:]]
        except OSError:
            lines = ["[Errore lettura log]"]
    else:
        lines = ["[Log non trovato – avvia il bot]"]
    return jsonify({"lines": lines})


@app.route("/api/control", methods=["POST"])
def api_control():
    data = request.get_json(silent=True) or {}
    action = data.get("action", "")
    if action not in ("start", "stop"):
        return jsonify({"ok": False, "error": "action deve essere 'start' o 'stop'"}), 400

    try:
        with open(CONTROL_FILE, "w", encoding="utf-8") as f:
            json.dump({"action": action}, f)
        return jsonify({"ok": True, "action": action})
    except OSError as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# ─── MAIN ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    port = int(os.environ.get("DASHBOARD_PORT", 5050))
    print(f"\n  Dashboard disponibile su  http://localhost:{port}\n")
    app.run(host="0.0.0.0", port=port, debug=False)
