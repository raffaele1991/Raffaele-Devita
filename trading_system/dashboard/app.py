"""
Dashboard – SMC+ML Trading Bot
================================
Server Flask locale che espone la dashboard web e le API di stato.

Avvio:
    python run_dashboard.py
    oppure
    python -m trading_system.dashboard.app

API:
    GET  /                    → dashboard HTML
    GET  /api/state           → stato corrente del bot (JSON)
    GET  /api/log             → ultime N righe di log (JSON)
    POST /api/control         → {"action": "stop"|"start"} per controllare il bot
    POST /api/data/download   → avvia download dati storici da MT5
    GET  /api/data/status     → stato del download
    GET  /api/data/files      → elenco CSV presenti in data/
    POST /api/train           → avvia training del modello ML
    GET  /api/train/status    → stato del training
"""

import os
import sys
import json
import glob
import subprocess
import threading
from pathlib import Path
from flask import Flask, jsonify, render_template, request

# ─── PATH ─────────────────────────────────────────────────────────────────────

ROOT         = Path(__file__).parent.parent.parent          # repo root
STATE_FILE   = ROOT / "trading_system" / "state.json"
CONTROL_FILE = ROOT / "trading_system" / "control.json"
LOG_FILE     = ROOT / "trading_system" / "trading.log"
DATA_DIR     = ROOT / "trading_system" / "data"
MODELS_DIR   = ROOT / "trading_system" / "models"

sys.path.insert(0, str(ROOT))

# Import downloader (lazy, per non bloccare avvio se MT5 non disponibile)
try:
    from trading_system.data.downloader import start_download, get_status as get_download_status
    _downloader_ok = True
except Exception:
    _downloader_ok = False
    def start_download(years=4): return False
    def get_download_status(): return {"running": False, "done": False, "error": "Downloader non disponibile", "symbols": {}}

# ─── TRAINING STATE ────────────────────────────────────────────────────────────

_train_lock  = threading.Lock()
_train_state = {"running": False, "done": False, "error": None, "output": [], "started_at": None}


def _run_training():
    """Esegue train.py in un subprocess e cattura l'output."""
    with _train_lock:
        _train_state["running"]    = True
        _train_state["done"]       = False
        _train_state["error"]      = None
        _train_state["output"]     = []
        _train_state["started_at"] = __import__("datetime").datetime.now().isoformat()

    train_script = ROOT / "trading_system" / "ml" / "train.py"
    try:
        proc = subprocess.Popen(
            [sys.executable, str(train_script)],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, cwd=str(ROOT)
        )
        for line in proc.stdout:
            line = line.rstrip()
            with _train_lock:
                _train_state["output"].append(line)
                # mantieni solo ultime 200 righe
                if len(_train_state["output"]) > 200:
                    _train_state["output"] = _train_state["output"][-200:]
        proc.wait()
        with _train_lock:
            if proc.returncode != 0:
                _train_state["error"] = f"Training terminato con errore (codice {proc.returncode})"
    except Exception as e:
        with _train_lock:
            _train_state["error"] = str(e)
    finally:
        with _train_lock:
            _train_state["running"] = False
            _train_state["done"]    = True

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


# ─── DATA DOWNLOAD ─────────────────────────────────────────────────────────────

@app.route("/api/data/download", methods=["POST"])
def api_data_download():
    data  = request.get_json(silent=True) or {}
    years = int(data.get("years", 4))
    years = max(1, min(years, 10))   # clamp 1-10

    started = start_download(years=years)
    if not started:
        return jsonify({"ok": False, "error": "Download già in corso"}), 409
    return jsonify({"ok": True, "years": years})


@app.route("/api/data/status")
def api_data_status():
    return jsonify(get_download_status())


@app.route("/api/data/files")
def api_data_files():
    """Elenca i CSV presenti in data/ con statistiche di base."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    files = []
    for csv_path in sorted(DATA_DIR.glob("*.csv")):
        info = {"name": csv_path.name, "rows": 0, "from": "", "to": "", "size_mb": 0}
        try:
            info["size_mb"] = round(csv_path.stat().st_size / 1024 / 1024, 2)
            df = __import__("pandas").read_csv(csv_path, index_col=0, parse_dates=True, nrows=1)
            # conta righe velocemente
            with open(csv_path, "rb") as f:
                info["rows"] = sum(1 for _ in f) - 1   # sottrai header
            df_dates = __import__("pandas").read_csv(csv_path, index_col=0, parse_dates=True,
                                                      usecols=[0])
            info["from"] = str(df_dates.index[0].date())
            info["to"]   = str(df_dates.index[-1].date())
        except Exception:
            pass
        files.append(info)
    return jsonify({"files": files})


# ─── TRAINING ──────────────────────────────────────────────────────────────────

@app.route("/api/train", methods=["POST"])
def api_train():
    with _train_lock:
        if _train_state["running"]:
            return jsonify({"ok": False, "error": "Training già in corso"}), 409

    thread = threading.Thread(target=_run_training, daemon=True)
    thread.start()
    return jsonify({"ok": True})


@app.route("/api/train/status")
def api_train_status():
    with _train_lock:
        import copy
        return jsonify(copy.deepcopy(_train_state))


@app.route("/api/models/files")
def api_models_files():
    """Elenca i modelli .pkl presenti in models/."""
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    models = []
    for p in sorted(MODELS_DIR.glob("*.pkl")):
        stat = p.stat()
        models.append({
            "name":     p.name,
            "size_mb":  round(stat.st_size / 1024 / 1024, 2),
            "modified": __import__("datetime").datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M"),
        })
    return jsonify({"models": models})


# ─── MAIN ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    port = int(os.environ.get("DASHBOARD_PORT", 5050))
    print(f"\n  Dashboard disponibile su  http://localhost:{port}\n")
    app.run(host="0.0.0.0", port=port, debug=False)
