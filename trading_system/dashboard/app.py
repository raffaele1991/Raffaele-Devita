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
    GET  /api/models/files    → elenco modelli .pkl
    POST /api/backtest        → avvia backtest {"symbol", "start_date", "end_date"}
    GET  /api/backtest/status → stato e risultati del backtest
    GET  /api/settings        → legge le impostazioni correnti (JSON)
    POST /api/settings        → salva le impostazioni e riscrive config.py
"""

import os
import sys
import json
import glob
import subprocess
import threading
import signal as _signal
from pathlib import Path
from flask import Flask, jsonify, render_template, request

# ─── PATH ─────────────────────────────────────────────────────────────────────

ROOT         = Path(__file__).parent.parent.parent          # repo root
STATE_FILE   = ROOT / "trading_system" / "state.json"
CONTROL_FILE = ROOT / "trading_system" / "control.json"
LOG_FILE     = ROOT / "trading_system" / "trading.log"
DATA_DIR     = ROOT / "trading_system" / "data"
MODELS_DIR   = ROOT / "trading_system" / "models"
CONFIG_FILE  = ROOT / "trading_system" / "config.py"
SETTINGS_FILE = ROOT / "trading_system" / "settings.json"
BOT_SCRIPT    = ROOT / "trading_system" / "bot.py"

sys.path.insert(0, str(ROOT))

# ─── BOT SUBPROCESS ───────────────────────────────────────────────────────────

_bot_proc: "subprocess.Popen | None" = None
_bot_lock = threading.Lock()


def _bot_running() -> bool:
    with _bot_lock:
        return _bot_proc is not None and _bot_proc.poll() is None


def _start_bot_proc() -> "tuple[bool, str]":
    global _bot_proc
    with _bot_lock:
        if _bot_proc is not None and _bot_proc.poll() is None:
            return False, "Bot già in esecuzione"
        try:
            _bot_proc = subprocess.Popen(
                [sys.executable, str(BOT_SCRIPT)],
                cwd=str(ROOT),
            )
            return True, ""
        except Exception as e:
            return False, str(e)


def _stop_bot_proc() -> "tuple[bool, str]":
    global _bot_proc
    with _bot_lock:
        if _bot_proc is None or _bot_proc.poll() is not None:
            return False, "Bot non in esecuzione"
        try:
            _bot_proc.terminate()
            try:
                _bot_proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                _bot_proc.kill()
            return True, ""
        except Exception as e:
            return False, str(e)

# Import downloader (lazy, per non bloccare avvio se MT5 non disponibile)
try:
    from trading_system.data.downloader import start_download, get_status as get_download_status
    _downloader_ok = True
except Exception:
    _downloader_ok = False
    def start_download(years=4): return False
    def get_download_status(): return {"running": False, "done": False, "error": "Downloader non disponibile", "symbols": {}}

# Import backtest engine (lazy)
try:
    from trading_system.backtest.engine import start_backtest, get_status as get_backtest_status
    _backtest_ok = True
except Exception:
    _backtest_ok = False
    def start_backtest(symbol, start_date, end_date): return False
    def get_backtest_status(): return {"running": False, "status": "error", "error": "Modulo backtest non disponibile", "progress": 0, "results": None, "log": []}

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
        "running":             False,
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
    proc_running = _bot_running()
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                state = json.load(f)
            # usa stato processo reale come fonte di verità
            state["running"] = proc_running
            if not proc_running:
                state["bot_status"] = "offline"
            return jsonify(state)
        except (json.JSONDecodeError, OSError):
            pass
    base = _default_state()
    base["running"] = proc_running
    return jsonify(base)


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

    if action == "start":
        ok, err = _start_bot_proc()
        if not ok:
            return jsonify({"ok": False, "error": err}), 409
        return jsonify({"ok": True, "action": "start"})
    else:
        # Scrivi control.json per shutdown pulito, poi termina il processo
        try:
            with open(CONTROL_FILE, "w", encoding="utf-8") as f:
                json.dump({"action": "stop"}, f)
        except OSError:
            pass
        ok, err = _stop_bot_proc()
        return jsonify({"ok": True, "action": "stop"})


# ─── DATA DOWNLOAD ─────────────────────────────────────────────────────────────

# Alias flat (usati dal frontend)
@app.route("/api/download_data", methods=["POST"])
def api_download_data_alias():
    return api_data_download()

@app.route("/api/download_status")
def api_download_status_alias():
    return api_data_status()

@app.route("/api/data_files")
def api_data_files_alias():
    return api_data_files()

@app.route("/api/train_status")
def api_train_status_alias():
    return api_train_status()

@app.route("/api/model_files")
def api_model_files_alias():
    return api_models_files()


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
            pd = __import__("pandas")
            df = pd.read_csv(csv_path, index_col=0, parse_dates=True, date_format="mixed", nrows=1)
            # conta righe velocemente
            with open(csv_path, "rb") as f:
                info["rows"] = sum(1 for _ in f) - 1   # sottrai header
            df_dates = pd.read_csv(csv_path, index_col=0, parse_dates=True,
                                   date_format="mixed", usecols=[0])
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


# ─── SETTINGS ─────────────────────────────────────────────────────────────────

_SETTINGS_DEFAULTS = {
    "mt5_account":               "",
    "mt5_password":              "",
    "mt5_server":                "",
    "symbols":                   ["XAUUSD", "EURUSD"],
    "session_london":            True,
    "session_ny":                True,
    "timeframe":                 "M5",
    "risk_per_trade_pct":        0.5,
    "max_trades_per_day":        3,
    "max_daily_dd_pct":          3.0,
    "max_total_dd_pct":          7.0,
    "min_rr":                    2.0,
    "ml_confidence_threshold":   0.65,
    "ml_enabled":                True,
    "telegram_token":            "",
    "telegram_chat_id":          "",
    "notify_trades":             True,
    "notify_warnings":           True,
    "notify_signals":            False,
}


def _load_settings() -> dict:
    if SETTINGS_FILE.exists():
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
            merged = dict(_SETTINGS_DEFAULTS)
            merged.update(saved)
            return merged
        except (json.JSONDecodeError, OSError):
            pass
    return dict(_SETTINGS_DEFAULTS)


def _patch_config(data: dict) -> None:
    """Riscrive le variabili chiave in config.py."""
    if not CONFIG_FILE.exists():
        return
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        lines = f.readlines()

    replacements = {
        "MT5_ACCOUNT":             str(int(data["mt5_account"])) if str(data.get("mt5_account", "")).strip().isdigit() else "0",
        "MT5_PASSWORD":            repr(data.get("mt5_password", "")),
        "MT5_SERVER":              repr(data.get("mt5_server", "")),
        "TELEGRAM_BOT_TOKEN":      repr(data.get("telegram_token", "")),
        "TELEGRAM_CHAT_ID":        repr(data.get("telegram_chat_id", "")),
        "RISK_PER_TRADE_PCT":      str(round(float(data.get("risk_per_trade_pct", 0.5)) / 100, 4)),
        "PROP_MAX_TRADES_PER_DAY": str(int(data.get("max_trades_per_day", 3))),
        "PROP_MAX_DAILY_LOSS_PCT": str(round(float(data.get("max_daily_dd_pct", 3.0)) / 100, 4)),
        "PROP_MAX_TOTAL_LOSS_PCT": str(round(float(data.get("max_total_dd_pct", 7.0)) / 100, 4)),
        "MIN_RISK_REWARD":         str(float(data.get("min_rr", 2.0))),
        "ML_CONFIDENCE_THRESHOLD": str(float(data.get("ml_confidence_threshold", 0.65))),
    }

    new_lines = []
    for line in lines:
        written = False
        for key, val in replacements.items():
            if line.startswith(key + " ") or line.startswith(key + "="):
                comment = ""
                if "#" in line:
                    comment = "  " + line[line.index("#"):]
                new_lines.append(f"{key} = {val}{comment if comment else ''}\n")
                written = True
                break
        if not written:
            new_lines.append(line)

    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        f.writelines(new_lines)


def _save_settings(data: dict) -> None:
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    _patch_config(data)


@app.route("/api/settings", methods=["GET"])
def api_settings_get():
    return jsonify(_load_settings())


@app.route("/api/settings", methods=["POST"])
def api_settings_post():
    data = request.get_json(silent=True) or {}
    current = _load_settings()
    current.update(data)
    try:
        _save_settings(current)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# ─── BACKTEST ──────────────────────────────────────────────────────────────────

VALID_SYMBOLS = {"XAUUSD", "EURUSD"}

@app.route("/api/backtest", methods=["POST"])
def api_backtest():
    data       = request.get_json(silent=True) or {}
    symbol     = data.get("symbol", "XAUUSD").upper()
    start_date = data.get("start_date", "").strip()
    end_date   = data.get("end_date", "").strip()

    if symbol not in VALID_SYMBOLS:
        return jsonify({"ok": False, "error": f"Simbolo non valido: {symbol}"}), 400
    if not start_date or not end_date:
        return jsonify({"ok": False, "error": "start_date e end_date sono obbligatori"}), 400
    if start_date >= end_date:
        return jsonify({"ok": False, "error": "start_date deve essere precedente a end_date"}), 400

    started = start_backtest(symbol, start_date, end_date)
    if not started:
        return jsonify({"ok": False, "error": "Backtest già in corso — attendi il completamento"}), 409

    return jsonify({"ok": True, "symbol": symbol, "start_date": start_date, "end_date": end_date})


@app.route("/api/backtest/status")
def api_backtest_status():
    return jsonify(get_backtest_status())


# ─── MAIN ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    port = int(os.environ.get("DASHBOARD_PORT", 5050))
    print(f"\n  Dashboard disponibile su  http://localhost:{port}\n")
    app.run(host="0.0.0.0", port=port, debug=False)
