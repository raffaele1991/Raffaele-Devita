"""GUI Web per Bug Bounty Scanner - App Flask."""

import json
import logging
import os
import threading
import time
from datetime import datetime
from pathlib import Path

from flask import Flask, render_template, request, redirect, url_for, jsonify, flash, session

from bugbounty_scanner.license_manager import (
    activate_license, get_active_license, verify_license_key, LicenseError
)

app = Flask(__name__)
app.secret_key = os.urandom(24)


@app.template_filter('timestamp_to_date')
def timestamp_to_date(ts):
    return datetime.fromtimestamp(ts).strftime('%d/%m/%Y')

# Stato scansioni in corso
scans = {}
scan_lock = threading.Lock()


def get_license_info():
    """Restituisce info licenza attiva o None."""
    return get_active_license()


def license_required(f):
    """Decoratore: richiede licenza attiva."""
    from functools import wraps

    @wraps(f)
    def decorated(*args, **kwargs):
        info = get_license_info()
        if not info:
            return redirect(url_for("activate"))
        return f(*args, **kwargs)

    return decorated


# ==================== ROUTES ====================


@app.route("/")
def index():
    info = get_license_info()
    if not info:
        return redirect(url_for("activate"))
    return redirect(url_for("dashboard"))


@app.route("/activate", methods=["GET", "POST"])
def activate():
    info = get_license_info()
    if request.method == "POST":
        key = request.form.get("license_key", "").strip()
        if not key:
            flash("Inserisci una chiave di licenza.", "error")
            return render_template("activate.html", license_info=info)
        try:
            info = activate_license(key)
            flash(f"Licenza {info['plan']} attivata con successo!", "success")
            return redirect(url_for("dashboard"))
        except LicenseError as e:
            flash(str(e), "error")
    return render_template("activate.html", license_info=info)


@app.route("/dashboard")
@license_required
def dashboard():
    info = get_license_info()
    days_left = (info["expiry"] - int(time.time())) // 86400
    return render_template(
        "dashboard.html",
        license_info=info,
        days_left=days_left,
        scans=scans,
        is_pro=info["plan_info"]["allow_pro"],
    )


@app.route("/scan", methods=["POST"])
@license_required
def start_scan():
    info = get_license_info()
    target = request.form.get("target", "").strip()
    mode = request.form.get("mode", "lite")
    modules = request.form.getlist("modules")

    if not target:
        flash("Inserisci un target.", "error")
        return redirect(url_for("dashboard"))

    if mode == "pro" and not info["plan_info"]["allow_pro"]:
        flash("La modalita PRO richiede una licenza PRO o ENTERPRISE.", "error")
        return redirect(url_for("dashboard"))

    # Crea scan ID
    scan_id = f"scan_{int(time.time())}_{target.replace('.', '_').replace('/', '_')[:30]}"

    scan_data = {
        "id": scan_id,
        "target": target,
        "mode": mode,
        "modules": modules,
        "status": "running",
        "started": datetime.now().strftime("%d/%m/%Y %H:%M"),
        "progress": 0,
        "current_step": "Avvio scansione...",
        "findings": [],
        "summary": None,
    }

    with scan_lock:
        scans[scan_id] = scan_data

    # Avvia la scansione in background
    thread = threading.Thread(target=run_scan_background, args=(scan_id, target, mode, modules))
    thread.daemon = True
    thread.start()

    return redirect(url_for("scan_status", scan_id=scan_id))


def run_scan_background(scan_id, target, mode, modules):
    """Esegue la scansione in un thread separato."""
    try:
        if mode == "lite":
            run_lite_scan(scan_id, target, modules)
        else:
            run_pro_scan(scan_id, target, modules)
    except Exception as e:
        with scan_lock:
            scans[scan_id]["status"] = "error"
            scans[scan_id]["current_step"] = f"Errore: {str(e)}"


def run_lite_scan(scan_id, target, modules):
    """Esegue scansione LITE."""
    from bugbounty_scanner.scanner import Scanner
    from bugbounty_scanner.modules.recon import ReconModule
    from bugbounty_scanner.modules.headers import HeadersModule
    from bugbounty_scanner.modules.xss import XSSModule
    from bugbounty_scanner.modules.sqli import SQLiModule
    from bugbounty_scanner.modules.ssrf import SSRFModule
    from bugbounty_scanner.modules.open_redirect import OpenRedirectModule
    from bugbounty_scanner.modules.sensitive_files import SensitiveFilesModule
    from bugbounty_scanner.http_session import HttpSession

    http_session = HttpSession(rate_limit=5)
    scanner = Scanner(target=target, threads=10, delay=0.5, modules=modules or None, verbose=False)

    all_modules = [
        ("recon", ReconModule(threads=10, http_session=http_session)),
        ("headers", HeadersModule(http_session=http_session)),
        ("xss", XSSModule(http_session=http_session)),
        ("sqli", SQLiModule(http_session=http_session)),
        ("ssrf", SSRFModule(http_session=http_session)),
        ("open_redirect", OpenRedirectModule(http_session=http_session)),
        ("sensitive_files", SensitiveFilesModule(threads=10, http_session=http_session)),
    ]

    total = len(all_modules)
    for i, (name, mod) in enumerate(all_modules):
        with scan_lock:
            scans[scan_id]["progress"] = int((i / total) * 100)
            scans[scan_id]["current_step"] = f"[{i + 1}/{total}] {name}..."
        scanner.register_module(mod)

    with scan_lock:
        scans[scan_id]["current_step"] = "Esecuzione scansione..."

    result = scanner.run()

    findings_list = []
    for f in result.findings:
        findings_list.append({
            "type": getattr(f, "vuln_type", "Unknown"),
            "severity": getattr(f, "severity", "INFO"),
            "url": getattr(f, "url", target),
            "description": getattr(f, "description", str(f)),
        })

    with scan_lock:
        scans[scan_id]["status"] = "completed"
        scans[scan_id]["progress"] = 100
        scans[scan_id]["current_step"] = "Completata"
        scans[scan_id]["findings"] = findings_list
        scans[scan_id]["summary"] = result.summary


def run_pro_scan(scan_id, target, modules):
    """Esegue scansione PRO."""
    from bugbounty_scanner.orchestrator import Orchestrator
    from bugbounty_scanner.tools.subfinder import SubfinderTool
    from bugbounty_scanner.tools.httpx_tool import HttpxTool
    from bugbounty_scanner.tools.nmap_tool import NmapTool
    from bugbounty_scanner.tools.nuclei_tool import NucleiTool
    from bugbounty_scanner.tools.ffuf_tool import FfufTool
    from bugbounty_scanner.tools.sqlmap_tool import SqlmapTool
    from bugbounty_scanner.tools.dalfox_tool import DalfoxTool
    from bugbounty_scanner.tools.nikto_tool import NiktoTool
    from bugbounty_scanner.modules.headers import HeadersModule
    from bugbounty_scanner.modules.sensitive_files import SensitiveFilesModule
    from bugbounty_scanner.modules.js_scanner import JSScanner
    from bugbounty_scanner.modules.crawler import CrawlerModule
    from bugbounty_scanner.modules.wayback import WaybackModule
    from bugbounty_scanner.http_session import HttpSession
    from bugbounty_scanner.cli_pro import InternalToolAdapterWithSession

    http_session = HttpSession(rate_limit=5)

    pipeline = modules if modules else [
        "subfinder", "httpx", "nmap", "crawler", "wayback", "ffuf",
        "js_scanner", "nuclei", "nikto", "dalfox", "sqlmap",
        "headers", "sensitive_files",
    ]

    orch = Orchestrator(target_url=target, pipeline=pipeline, skip_missing=True)

    orch.register("subfinder", SubfinderTool())
    orch.register("httpx", HttpxTool())
    orch.register("nmap", NmapTool())
    orch.register("ffuf", FfufTool())
    orch.register("nuclei", NucleiTool())
    orch.register("nikto", NiktoTool())
    orch.register("dalfox", DalfoxTool())
    orch.register("sqlmap", SqlmapTool())
    orch.register("crawler", InternalToolAdapterWithSession(CrawlerModule, http_session))
    orch.register("wayback", InternalToolAdapterWithSession(WaybackModule, http_session))
    orch.register("js_scanner", InternalToolAdapterWithSession(JSScanner, http_session))
    orch.register("headers", InternalToolAdapterWithSession(HeadersModule, http_session))
    orch.register("sensitive_files", InternalToolAdapterWithSession(SensitiveFilesModule, http_session))

    total = len(pipeline)
    for i, step in enumerate(pipeline):
        with scan_lock:
            scans[scan_id]["progress"] = int((i / total) * 100)
            scans[scan_id]["current_step"] = f"[{i + 1}/{total}] {step}..."

    result = orch.run()

    findings_list = []
    for f in result.findings:
        findings_list.append({
            "type": getattr(f, "vuln_type", "Unknown"),
            "severity": getattr(f, "severity", "INFO"),
            "url": getattr(f, "url", target),
            "description": getattr(f, "description", str(f)),
        })

    with scan_lock:
        scans[scan_id]["status"] = "completed"
        scans[scan_id]["progress"] = 100
        scans[scan_id]["current_step"] = "Completata"
        scans[scan_id]["findings"] = findings_list
        scans[scan_id]["summary"] = result.summary


@app.route("/scan/<scan_id>")
@license_required
def scan_status(scan_id):
    info = get_license_info()
    scan = scans.get(scan_id)
    if not scan:
        flash("Scansione non trovata.", "error")
        return redirect(url_for("dashboard"))
    return render_template("scan_status.html", scan=scan, license_info=info)


@app.route("/api/scan/<scan_id>")
def api_scan_status(scan_id):
    """API per aggiornamento live dello stato scansione."""
    scan = scans.get(scan_id)
    if not scan:
        return jsonify({"error": "Scansione non trovata"}), 404
    return jsonify(scan)


@app.route("/results")
@license_required
def results():
    info = get_license_info()
    completed = {k: v for k, v in scans.items() if v["status"] == "completed"}
    return render_template("results.html", scans=completed, license_info=info)


def main():
    print("""
  ============================================
   Bug Bounty Scanner - GUI Web
  ============================================
   Apri il browser su: http://127.0.0.1:5000
  ============================================
""")
    app.run(host="127.0.0.1", port=5000, debug=False)


if __name__ == "__main__":
    main()
