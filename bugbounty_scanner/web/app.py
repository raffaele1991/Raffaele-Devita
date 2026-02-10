"""GUI Web per Bug Bounty Scanner - App Flask."""

import json
import logging
import os
import threading
import time
from datetime import datetime
from pathlib import Path

from flask import Flask, render_template, request, redirect, url_for, jsonify, flash, session, send_file

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


# Impostazioni persistenti (Telegram, Discord, ecc.)
saved_settings = {}


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
        settings=saved_settings,
    )


@app.route("/settings", methods=["GET", "POST"])
@license_required
def settings():
    info = get_license_info()
    if request.method == "POST":
        saved_settings["telegram_token"] = request.form.get("telegram_token", "").strip()
        saved_settings["telegram_chat"] = request.form.get("telegram_chat", "").strip()
        saved_settings["discord_webhook"] = request.form.get("discord_webhook", "").strip()
        saved_settings["default_header"] = request.form.get("default_header", "").strip()
        saved_settings["default_email"] = request.form.get("default_email", "").strip()
        saved_settings["default_rate_limit"] = request.form.get("default_rate_limit", "5").strip()
        flash("Impostazioni salvate!", "success")
        return redirect(url_for("settings"))
    return render_template("settings.html", license_info=info, settings=saved_settings)


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

    # Raccogli tutte le opzioni dal form
    scan_options = {
        "program_url": request.form.get("program_url", "").strip(),
        "scope_text": request.form.get("scope_text", "").strip(),
        "custom_header": request.form.get("custom_header", "").strip(),
        "email": request.form.get("email", "").strip(),
        "rate_limit": float(request.form.get("rate_limit", 5)),
        "telegram_token": request.form.get("telegram_token", "").strip(),
        "telegram_chat": request.form.get("telegram_chat", "").strip(),
        "discord_webhook": request.form.get("discord_webhook", "").strip(),
        "notify_severity": request.form.get("notify_severity", "MEDIUM"),
        "nuclei_severity": request.form.get("nuclei_severity", "").strip(),
        "nuclei_tags": request.form.get("nuclei_tags", "").strip(),
        "nuclei_templates": request.form.get("nuclei_templates", "").strip(),
        "nuclei_rate": int(request.form.get("nuclei_rate", 100)),
        "nmap_scan": request.form.get("nmap_scan", "default"),
        "sqlmap_level": int(request.form.get("sqlmap_level", 1)),
        "sqlmap_risk": int(request.form.get("sqlmap_risk", 1)),
        "crawl_depth": int(request.form.get("crawl_depth", 3)),
        "crawl_pages": int(request.form.get("crawl_pages", 100)),
        "ffuf_wordlist": request.form.get("ffuf_wordlist", "").strip(),
        "ffuf_threads": int(request.form.get("ffuf_threads", 40)),
        "report_formats": request.form.getlist("report_format"),
        "output_dir": request.form.get("output_dir", "reports").strip(),
    }

    # Crea scan ID
    scan_id = f"scan_{int(time.time())}_{target.replace('.', '_').replace('/', '_')[:30]}"

    scan_data = {
        "id": scan_id,
        "target": target,
        "mode": mode,
        "modules": modules,
        "options": scan_options,
        "status": "running",
        "started": datetime.now().strftime("%d/%m/%Y %H:%M"),
        "progress": 0,
        "current_step": "Avvio scansione...",
        "findings": [],
        "summary": None,
        "report_paths": {},
        "_start_time": time.time(),
    }

    with scan_lock:
        scans[scan_id] = scan_data

    # Avvia la scansione in background
    thread = threading.Thread(target=run_scan_background, args=(scan_id, target, mode, modules, scan_options))
    thread.daemon = True
    thread.start()

    return redirect(url_for("scan_status", scan_id=scan_id))


def run_scan_background(scan_id, target, mode, modules, options):
    """Esegue la scansione in un thread separato."""
    try:
        if mode == "lite":
            run_lite_scan(scan_id, target, modules, options)
        else:
            run_pro_scan(scan_id, target, modules, options)

        # Genera report
        generate_reports(scan_id, options)

        # Invia notifiche
        send_notifications(scan_id, options)

    except Exception as e:
        with scan_lock:
            scans[scan_id]["status"] = "error"
            scans[scan_id]["current_step"] = f"Errore: {str(e)}"


def _create_http_session(options):
    """Crea sessione HTTP con le opzioni dalla GUI."""
    from bugbounty_scanner.http_session import HttpSession, parse_headers_list

    custom_headers = {}
    header_str = options.get("custom_header", "")
    if header_str and ":" in header_str:
        key, val = header_str.split(":", 1)
        custom_headers[key.strip()] = val.strip()

    return HttpSession(
        headers=custom_headers,
        email=options.get("email", ""),
        rate_limit=options.get("rate_limit", 5),
    )


def _setup_scope(options):
    """Configura lo scope dal programma BB o dal testo."""
    program_url = options.get("program_url", "")
    scope_text = options.get("scope_text", "")

    if not program_url and not scope_text:
        return None

    from bugbounty_scanner.program_parser import ProgramParser
    from bugbounty_scanner.scope_checker import ScopeChecker

    parser = ProgramParser()
    if program_url:
        program_info = parser.parse(program_url)
    else:
        # Crea scope da testo
        import tempfile
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write(scope_text)
            f.flush()
            program_info = parser.parse(f.name)

    return ScopeChecker(program_info)


def generate_reports(scan_id, options):
    """Genera i report nei formati richiesti."""
    scan = scans.get(scan_id)
    if not scan or scan["status"] != "completed":
        return

    try:
        from bugbounty_scanner.reporter import Reporter

        class SimpleResult:
            """Oggetto compatibile con Reporter che wrappa i dati della scansione GUI."""
            def __init__(self, scan_data):
                self.findings = scan_data.get("_raw_findings", [])
                self.target = scan_data.get("target", "unknown")
                self.subdomains = scan_data.get("_subdomains", [])
                self.open_ports = scan_data.get("_open_ports", [])
                self.technologies = scan_data.get("_technologies", [])
                self.errors = scan_data.get("_errors", [])
                self._summary = scan_data.get("summary", {})
                # Calcola durata dalla data di avvio
                self.start_time = scan_data.get("_start_time", 0)
                self.end_time = scan_data.get("_end_time", time.time())

            @property
            def duration(self):
                return self.end_time - self.start_time if self.start_time else 0

            @property
            def summary(self):
                return self._summary

        result = SimpleResult(scan)
        reporter = Reporter(result, output_dir=options.get("output_dir", "reports"))

        formats = options.get("report_formats", ["html", "json"])
        if not formats:
            formats = ["html", "json"]
        paths = {}
        for fmt in formats:
            if fmt == "json":
                paths["json"] = reporter.generate_json()
            elif fmt == "html":
                paths["html"] = reporter.generate_html()
            elif fmt == "markdown":
                paths["markdown"] = reporter.generate_markdown()

        with scan_lock:
            scans[scan_id]["report_paths"] = paths

        logger.info(f"Report generati: {paths}")
    except Exception as e:
        logger.error(f"Errore generazione report per {scan_id}: {e}")
        import traceback
        traceback.print_exc()


def send_notifications(scan_id, options):
    """Invia notifiche Telegram/Discord."""
    scan = scans.get(scan_id)
    if not scan or scan["status"] != "completed":
        return

    telegram_token = options.get("telegram_token", "")
    telegram_chat = options.get("telegram_chat", "")
    discord_webhook = options.get("discord_webhook", "")

    if not telegram_token and not discord_webhook:
        return

    try:
        from bugbounty_scanner.notifier import NotificationManager

        notifier = NotificationManager()
        if telegram_token and telegram_chat:
            notifier.add_telegram(telegram_token, telegram_chat)
        if discord_webhook:
            notifier.add_discord(discord_webhook)

        notifier.set_min_severity(options.get("notify_severity", "MEDIUM"))

        for finding in scan.get("_raw_findings", []):
            notifier.notify_finding(finding)
    except Exception:
        pass


def run_lite_scan(scan_id, target, modules, options):
    """Esegue scansione LITE con tutte le opzioni."""
    from bugbounty_scanner.scanner import Scanner
    from bugbounty_scanner.modules.recon import ReconModule
    from bugbounty_scanner.modules.headers import HeadersModule
    from bugbounty_scanner.modules.xss import XSSModule
    from bugbounty_scanner.modules.sqli import SQLiModule
    from bugbounty_scanner.modules.ssrf import SSRFModule
    from bugbounty_scanner.modules.open_redirect import OpenRedirectModule
    from bugbounty_scanner.modules.sensitive_files import SensitiveFilesModule

    http_session = _create_http_session(options)
    scope_checker = _setup_scope(options)

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

    # Filtra risultati fuori scope
    if scope_checker:
        result.findings = [f for f in result.findings if scope_checker.check(getattr(f, 'url', target))]

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
        scans[scan_id]["_raw_findings"] = result.findings
        scans[scan_id]["_subdomains"] = getattr(result, "subdomains", [])
        scans[scan_id]["_open_ports"] = getattr(result, "open_ports", [])
        scans[scan_id]["_technologies"] = getattr(result, "technologies", [])
        scans[scan_id]["_errors"] = getattr(result, "errors", [])
        scans[scan_id]["_start_time"] = getattr(result, "start_time", 0)
        scans[scan_id]["_end_time"] = getattr(result, "end_time", time.time())


def run_pro_scan(scan_id, target, modules, options):
    """Esegue scansione PRO con tutte le opzioni."""
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
    from bugbounty_scanner.cli_pro import InternalToolAdapterWithSession

    http_session = _create_http_session(options)
    scope_checker = _setup_scope(options)

    pipeline = modules if modules else [
        "subfinder", "httpx", "nmap", "crawler", "wayback", "ffuf",
        "js_scanner", "nuclei", "nikto", "dalfox", "sqlmap",
        "headers", "sensitive_files",
    ]

    orch = Orchestrator(target_url=target, pipeline=pipeline, skip_missing=True)

    # Tool con opzioni dalla GUI
    orch.register("subfinder", SubfinderTool())
    orch.register("httpx", HttpxTool())
    orch.register("nmap", NmapTool(scan_type=options.get("nmap_scan", "default")))
    orch.register("ffuf", FfufTool(
        wordlist=options.get("ffuf_wordlist") or None,
        threads=options.get("ffuf_threads", 40),
    ))
    orch.register("nuclei", NucleiTool(
        severity_filter=options.get("nuclei_severity") or None,
        tags=options.get("nuclei_tags") or None,
        templates=options.get("nuclei_templates") or None,
        rate_limit=options.get("nuclei_rate", 100),
    ))
    orch.register("nikto", NiktoTool())
    orch.register("dalfox", DalfoxTool())
    orch.register("sqlmap", SqlmapTool(
        level=options.get("sqlmap_level", 1),
        risk=options.get("sqlmap_risk", 1),
    ))
    orch.register("crawler", InternalToolAdapterWithSession(
        CrawlerModule, http_session,
        max_pages=options.get("crawl_pages", 100),
        max_depth=options.get("crawl_depth", 3),
    ))
    orch.register("wayback", InternalToolAdapterWithSession(WaybackModule, http_session))
    orch.register("js_scanner", InternalToolAdapterWithSession(JSScanner, http_session))
    orch.register("headers", InternalToolAdapterWithSession(HeadersModule, http_session))
    orch.register("sensitive_files", InternalToolAdapterWithSession(SensitiveFilesModule, http_session))

    # Header per tool esterni
    all_headers = {}
    header_str = options.get("custom_header", "")
    if header_str and ":" in header_str:
        key, val = header_str.split(":", 1)
        all_headers[key.strip()] = val.strip()
    email = options.get("email", "")
    if email:
        all_headers.setdefault("X-Bug-Bounty-Contact", email)

    for name in pipeline:
        tool = orch._tools.get(name)
        if tool and hasattr(tool, "set_headers") and all_headers:
            tool.set_headers(all_headers)

    total = len(pipeline)
    for i, step in enumerate(pipeline):
        with scan_lock:
            scans[scan_id]["progress"] = int((i / total) * 100)
            scans[scan_id]["current_step"] = f"[{i + 1}/{total}] {step}..."

    result = orch.run()

    # Filtra risultati fuori scope
    if scope_checker:
        result.findings = [f for f in result.findings if scope_checker.check(getattr(f, 'url', target))]

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
        scans[scan_id]["_raw_findings"] = result.findings
        scans[scan_id]["_subdomains"] = getattr(result, "subdomains", [])
        scans[scan_id]["_open_ports"] = getattr(result, "open_ports", [])
        scans[scan_id]["_technologies"] = getattr(result, "technologies", [])
        scans[scan_id]["_errors"] = getattr(result, "errors", [])
        scans[scan_id]["_start_time"] = getattr(result, "start_time", 0)
        scans[scan_id]["_end_time"] = getattr(result, "end_time", time.time())


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
    # Escludi campi interni non serializzabili in JSON
    safe_data = {k: v for k, v in scan.items() if not k.startswith("_")}
    return jsonify(safe_data)


@app.route("/download/<scan_id>/<fmt>")
@license_required
def download_report(scan_id, fmt):
    """Scarica un report generato."""
    scan = scans.get(scan_id)
    if not scan:
        flash("Scansione non trovata.", "error")
        return redirect(url_for("dashboard"))
    report_path = scan.get("report_paths", {}).get(fmt)
    if not report_path or not os.path.isfile(report_path):
        flash(f"Report {fmt} non trovato.", "error")
        return redirect(url_for("scan_status", scan_id=scan_id))
    return send_file(report_path, as_attachment=True)


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
