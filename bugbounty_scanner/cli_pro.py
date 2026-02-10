#!/usr/bin/env python3
"""CLI Pro - interfaccia per l'orchestratore con tool professionali."""

import argparse
import logging
import sys
import urllib3

from bugbounty_scanner.license_manager import check_license
from bugbounty_scanner.orchestrator import Orchestrator, DEFAULT_PIPELINE
from bugbounty_scanner.reporter import Reporter

# Tool professionali
from bugbounty_scanner.tools.subfinder import SubfinderTool
from bugbounty_scanner.tools.httpx_tool import HttpxTool
from bugbounty_scanner.tools.nmap_tool import NmapTool
from bugbounty_scanner.tools.nuclei_tool import NucleiTool
from bugbounty_scanner.tools.ffuf_tool import FfufTool
from bugbounty_scanner.tools.sqlmap_tool import SqlmapTool
from bugbounty_scanner.tools.dalfox_tool import DalfoxTool
from bugbounty_scanner.tools.nikto_tool import NiktoTool

# Moduli interni
from bugbounty_scanner.modules.headers import HeadersModule
from bugbounty_scanner.modules.sensitive_files import SensitiveFilesModule
from bugbounty_scanner.modules.js_scanner import JSScanner
from bugbounty_scanner.modules.crawler import CrawlerModule
from bugbounty_scanner.modules.wayback import WaybackModule

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BANNER = r"""
  ____              ____                    _
 | __ ) _   _  __ _| __ )  ___  _   _ _ __ | |_ _   _
 |  _ \| | | |/ _` |  _ \ / _ \| | | | '_ \| __| | | |
 | |_) | |_| | (_| | |_) | (_) | |_| | | | | |_| |_| |
 |____/ \__,_|\__, |____/ \___/ \__,_|_| |_|\__|\__, |
              |___/                              |___/
      ____                              ____  ____   ___
     / ___|  ___ __ _ _ __  _ __   ___ |  _ \|  _ \ / _ \
     \___ \ / __/ _` | '_ \| '_ \ / _ \| |_) | |_) | | | |
      ___) | (_| (_| | | | | | | |  __/|  __/|  _ <| |_| |
     |____/ \___\__,_|_| |_|_| |_|\___||_|   |_| \_\\___/

    Bug Bounty Scanner PRO v2.0
    Con: Scope Auto + JS Scanner + Crawler + Wayback + Notifiche
"""

# Pipeline aggiornata con i nuovi moduli
FULL_PIPELINE = [
    "subfinder", "httpx", "nmap", "crawler", "wayback", "ffuf",
    "js_scanner", "nuclei", "nikto", "dalfox", "sqlmap",
    "headers", "sensitive_files",
]


class InternalToolAdapter:
    """Adatta i moduli interni all'interfaccia dei tool pro."""

    def __init__(self, module):
        self._module = module
        self.name = module.name
        self.binary = "python"

    def is_installed(self):
        return True

    def run(self, target, scan_result):
        return self._module.run(target.base_url, scan_result)


class InternalToolAdapterWithSession(InternalToolAdapter):
    """Adapter che passa anche la sessione HTTP ai moduli interni."""

    def __init__(self, module_class, http_session, **kwargs):
        module = module_class(http_session=http_session, **kwargs)
        super().__init__(module)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Bug Bounty Scanner PRO v2.0 - Orchestratore con tool professionali",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Esempi:
  %(prog)s -t example.com                                              Scansione completa
  %(prog)s -t example.com --program https://hackerone.com/example      Con scope automatico
  %(prog)s -t example.com --scope scope.txt                            Scope da file
  %(prog)s -t example.com --telegram-token TOKEN --telegram-chat ID    Con notifiche Telegram
  %(prog)s -t example.com --discord-webhook URL                        Con notifiche Discord
  %(prog)s -t example.com -H "X-Bug-Bounty: kobraraf91" --rate-limit 5
        """,
    )

    parser.add_argument("-t", "--target", required=True, help="URL o dominio target")
    parser.add_argument(
        "--pipeline", nargs="+", default=None,
        help=f"Tool da eseguire in ordine (default: tutti).",
    )
    parser.add_argument("--check", action="store_true", help="Verifica tool installati ed esci")
    parser.add_argument("--strict", action="store_true", help="Fallisci se un tool manca")

    # Programma Bug Bounty
    prog_group = parser.add_argument_group("Programma Bug Bounty")
    prog_group.add_argument(
        "--program", default=None,
        help="URL del programma bug bounty (HackerOne, Intigriti, Bugcrowd). Estrae scope automaticamente.",
    )
    prog_group.add_argument(
        "--scope", default=None,
        help="File con scope (un dominio per riga). Alternativa a --program.",
    )

    # Identificazione Bug Bounty
    bb_group = parser.add_argument_group("Identificazione")
    bb_group.add_argument(
        "-H", "--header", action="append", metavar="'Nome: Valore'",
        help="Header HTTP custom (ripetibile). Es: -H 'X-Bug-Bounty: kobraraf91'",
    )
    bb_group.add_argument(
        "--email", default=None,
        help="Email identificativa (es: kobraraf91@intigriti.me)",
    )
    bb_group.add_argument(
        "--rate-limit", type=float, default=5,
        help="Max richieste al secondo (default: 5)",
    )

    # Notifiche
    notif_group = parser.add_argument_group("Notifiche")
    notif_group.add_argument("--telegram-token", default=None, help="Token del bot Telegram")
    notif_group.add_argument("--telegram-chat", default=None, help="Chat ID Telegram")
    notif_group.add_argument("--discord-webhook", default=None, help="URL webhook Discord")
    notif_group.add_argument(
        "--notify-severity", default="MEDIUM",
        choices=["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"],
        help="Gravità minima per le notifiche (default: MEDIUM)",
    )

    # Crawler
    crawl_group = parser.add_argument_group("Crawler")
    crawl_group.add_argument("--crawl-depth", type=int, default=3, help="Profondità crawling (default: 3)")
    crawl_group.add_argument("--crawl-pages", type=int, default=100, help="Max pagine da crawlare (default: 100)")

    # Opzioni Nuclei
    nuclei_group = parser.add_argument_group("Nuclei")
    nuclei_group.add_argument("--nuclei-severity", default=None, help="Filtro gravità Nuclei")
    nuclei_group.add_argument("--nuclei-tags", default=None, help="Filtro tag Nuclei")
    nuclei_group.add_argument("--nuclei-templates", default=None, help="Template Nuclei custom")
    nuclei_group.add_argument("--nuclei-rate", type=int, default=100, help="Rate limit Nuclei")

    # Opzioni Nmap
    nmap_group = parser.add_argument_group("Nmap")
    nmap_group.add_argument("--nmap-scan", choices=["quick", "default", "full"], default="default")

    # Opzioni SQLMap
    sqlmap_group = parser.add_argument_group("SQLMap")
    sqlmap_group.add_argument("--sqlmap-level", type=int, default=1, choices=[1, 2, 3, 4, 5])
    sqlmap_group.add_argument("--sqlmap-risk", type=int, default=1, choices=[1, 2, 3])

    # Opzioni ffuf
    ffuf_group = parser.add_argument_group("ffuf")
    ffuf_group.add_argument("--ffuf-wordlist", default=None, help="Wordlist custom per ffuf")
    ffuf_group.add_argument("--ffuf-threads", type=int, default=40)

    # Output
    output_group = parser.add_argument_group("Output")
    output_group.add_argument("-o", "--output-dir", default="reports")
    output_group.add_argument("-f", "--format", nargs="+", choices=["json", "html", "markdown", "all"], default=["all"])
    output_group.add_argument("-v", "--verbose", action="store_true")
    output_group.add_argument("-q", "--quiet", action="store_true")

    return parser.parse_args()


def main():
    args = parse_args()

    level = logging.DEBUG if args.verbose else (logging.ERROR if args.quiet else logging.INFO)
    logging.basicConfig(level=level, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")

    if not args.quiet:
        print(BANNER)

    # Verifica licenza (richiede PRO o ENTERPRISE)
    license_info = check_license(require_pro=True)
    print(f"  Licenza {license_info['plan']} attiva ({license_info['email']})")

    # ==================== SCOPE DEL PROGRAMMA ====================
    program_info = None
    scope_checker = None

    if args.program or args.scope:
        from bugbounty_scanner.program_parser import ProgramParser
        from bugbounty_scanner.scope_checker import ScopeChecker

        parser = ProgramParser()
        source = args.program or args.scope
        print(f"  Caricamento scope da: {source}")
        program_info = parser.parse(source)
        print(program_info.summary())

        scope_checker = ScopeChecker(program_info)

    # ==================== SESSIONE HTTP ====================
    from bugbounty_scanner.http_session import HttpSession, parse_headers_list

    custom_headers = parse_headers_list(args.header)
    http_session = HttpSession(
        headers=custom_headers,
        email=args.email,
        rate_limit=args.rate_limit,
    )

    if custom_headers:
        print("  Header custom:")
        for k, v in custom_headers.items():
            print(f"    {k}: {v}")
    if args.email:
        print(f"  Email: {args.email}")
    print(f"  Rate limit: {args.rate_limit} req/sec")

    # ==================== NOTIFICHE ====================
    from bugbounty_scanner.notifier import NotificationManager

    notifier = NotificationManager()

    if args.telegram_token and args.telegram_chat:
        notifier.add_telegram(args.telegram_token, args.telegram_chat)
        print("  Notifiche Telegram: configurate")

    if args.discord_webhook:
        notifier.add_discord(args.discord_webhook)
        print("  Notifiche Discord: configurate")

    notifier.set_min_severity(args.notify_severity)

    # ==================== ORCHESTRATORE ====================
    pipeline = args.pipeline or FULL_PIPELINE
    orch = Orchestrator(
        target_url=args.target,
        pipeline=pipeline,
        skip_missing=True,
    )

    # Header per tool esterni
    all_headers = dict(custom_headers)
    if args.email:
        all_headers.setdefault("X-Bug-Bounty-Contact", args.email)
        all_headers.setdefault("From", args.email)

    def register_tool(name, tool):
        if hasattr(tool, "set_headers"):
            tool.set_headers(all_headers)
        orch.register(name, tool)

    # Tool professionali
    register_tool("subfinder", SubfinderTool())
    register_tool("httpx", HttpxTool())
    register_tool("nmap", NmapTool(scan_type=args.nmap_scan))
    register_tool("ffuf", FfufTool(wordlist=args.ffuf_wordlist, threads=args.ffuf_threads))
    register_tool("nuclei", NucleiTool(
        severity_filter=args.nuclei_severity, tags=args.nuclei_tags,
        templates=args.nuclei_templates, rate_limit=args.nuclei_rate,
    ))
    register_tool("nikto", NiktoTool())
    register_tool("dalfox", DalfoxTool())
    register_tool("sqlmap", SqlmapTool(level=args.sqlmap_level, risk=args.sqlmap_risk))

    # Moduli interni nuovi
    orch.register("crawler", InternalToolAdapterWithSession(
        CrawlerModule, http_session, max_pages=args.crawl_pages, max_depth=args.crawl_depth,
    ))
    orch.register("wayback", InternalToolAdapterWithSession(WaybackModule, http_session))
    orch.register("js_scanner", InternalToolAdapterWithSession(JSScanner, http_session))
    orch.register("headers", InternalToolAdapterWithSession(HeadersModule, http_session))
    orch.register("sensitive_files", InternalToolAdapterWithSession(SensitiveFilesModule, http_session))

    # Solo check?
    if args.check:
        orch.check_tools()
        sys.exit(0)

    # Verifica e scansiona
    print()
    installed, missing = orch.check_tools()

    try:
        result = orch.run()
    except KeyboardInterrupt:
        print("\n\n  Scansione interrotta dall'utente.")
        sys.exit(1)

    # Filtra risultati fuori scope
    if scope_checker:
        in_scope_findings = []
        for f in result.findings:
            if scope_checker.check(f.url):
                in_scope_findings.append(f)
        blocked = len(result.findings) - len(in_scope_findings)
        if blocked > 0:
            print(f"\n  Scope: {blocked} finding fuori scope filtrati")
        result.findings = in_scope_findings
        print(f"  {scope_checker.summary()}")

    # Notifiche per i finding
    if notifier.is_configured:
        for finding in result.findings:
            notifier.notify_finding(finding)
        notifier.notify_scan_complete(result)

    # Report
    reporter = Reporter(result, output_dir=args.output_dir)
    reporter.print_summary()

    formats = args.format
    if "all" in formats:
        paths = reporter.generate_all()
        for fmt, path in paths.items():
            print(f"  Report {fmt.upper()}: {path}")
    else:
        for fmt in formats:
            if fmt == "json":
                path = reporter.generate_json()
            elif fmt == "html":
                path = reporter.generate_html()
            elif fmt == "markdown":
                path = reporter.generate_markdown()
            print(f"  Report {fmt.upper()}: {path}")

    print()

    # Exit code
    sev = result.summary["by_severity"]
    if sev.get("CRITICAL", 0) > 0 or sev.get("HIGH", 0) > 0:
        sys.exit(2)
    elif sev.get("MEDIUM", 0) > 0:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
