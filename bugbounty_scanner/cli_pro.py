#!/usr/bin/env python3
"""CLI Pro - interfaccia per l'orchestratore con tool professionali."""

import argparse
import logging
import sys
import urllib3

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

    Bug Bounty Scanner PRO - Orchestratore Tool Professionali
    Subfinder + httpx + Nmap + ffuf + Nuclei + Nikto + Dalfox + SQLMap
"""


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


def parse_args():
    parser = argparse.ArgumentParser(
        description="Bug Bounty Scanner PRO - Orchestratore con tool professionali",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Esempi:
  %(prog)s -t example.com                          Scansione completa
  %(prog)s -t example.com --pipeline subfinder httpx nuclei   Solo questi tool
  %(prog)s -t example.com --check                  Verifica tool installati
  %(prog)s -t "https://example.com/page?id=1"      Con parametri per SQLMap/Dalfox
  %(prog)s -t example.com --nuclei-severity critical,high     Solo vulnerabilità gravi
  %(prog)s -t example.com --nmap-scan full          Scansione porte completa
        """,
    )

    parser.add_argument("-t", "--target", required=True, help="URL o dominio target")
    parser.add_argument(
        "--pipeline", nargs="+", choices=DEFAULT_PIPELINE, default=None,
        help=f"Tool da eseguire in ordine (default: tutti). Opzioni: {', '.join(DEFAULT_PIPELINE)}",
    )
    parser.add_argument("--check", action="store_true", help="Verifica quali tool sono installati ed esci")
    parser.add_argument("--strict", action="store_true", help="Fallisci se un tool non è installato")

    # Opzioni Nuclei
    nuclei_group = parser.add_argument_group("Nuclei")
    nuclei_group.add_argument("--nuclei-severity", default=None, help="Filtro gravità (es: critical,high,medium)")
    nuclei_group.add_argument("--nuclei-tags", default=None, help="Filtro tag (es: cve,misconfig,exposure)")
    nuclei_group.add_argument("--nuclei-templates", default=None, help="Path a template Nuclei custom")
    nuclei_group.add_argument("--nuclei-rate", type=int, default=100, help="Rate limit Nuclei (default: 100)")

    # Opzioni Nmap
    nmap_group = parser.add_argument_group("Nmap")
    nmap_group.add_argument("--nmap-scan", choices=["quick", "default", "full"], default="default",
                            help="Tipo scansione Nmap (default: default)")

    # Opzioni SQLMap
    sqlmap_group = parser.add_argument_group("SQLMap")
    sqlmap_group.add_argument("--sqlmap-level", type=int, default=1, choices=[1, 2, 3, 4, 5],
                              help="Livello test SQLMap 1-5 (default: 1)")
    sqlmap_group.add_argument("--sqlmap-risk", type=int, default=1, choices=[1, 2, 3],
                              help="Livello rischio SQLMap 1-3 (default: 1)")

    # Opzioni ffuf
    ffuf_group = parser.add_argument_group("ffuf")
    ffuf_group.add_argument("--ffuf-wordlist", default=None, help="Wordlist custom per ffuf")
    ffuf_group.add_argument("--ffuf-threads", type=int, default=40, help="Thread ffuf (default: 40)")

    # Output
    output_group = parser.add_argument_group("Output")
    output_group.add_argument("-o", "--output-dir", default="reports", help="Cartella report (default: reports)")
    output_group.add_argument("-f", "--format", nargs="+", choices=["json", "html", "markdown", "all"],
                              default=["all"], help="Formato report")
    output_group.add_argument("-v", "--verbose", action="store_true", help="Output dettagliato")
    output_group.add_argument("-q", "--quiet", action="store_true", help="Output minimo")

    return parser.parse_args()


def main():
    args = parse_args()

    level = logging.DEBUG if args.verbose else (logging.ERROR if args.quiet else logging.INFO)
    logging.basicConfig(level=level, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")

    if not args.quiet:
        print(BANNER)

    # Crea l'orchestratore
    pipeline = args.pipeline or DEFAULT_PIPELINE
    orch = Orchestrator(
        target_url=args.target,
        pipeline=pipeline,
        skip_missing=not args.strict,
    )

    # Registra i tool professionali
    orch.register("subfinder", SubfinderTool())
    orch.register("httpx", HttpxTool())
    orch.register("nmap", NmapTool(scan_type=args.nmap_scan))
    orch.register("ffuf", FfufTool(
        wordlist=args.ffuf_wordlist,
        threads=args.ffuf_threads,
    ))
    orch.register("nuclei", NucleiTool(
        severity_filter=args.nuclei_severity,
        tags=args.nuclei_tags,
        templates=args.nuclei_templates,
        rate_limit=args.nuclei_rate,
    ))
    orch.register("nikto", NiktoTool())
    orch.register("dalfox", DalfoxTool())
    orch.register("sqlmap", SqlmapTool(
        level=args.sqlmap_level,
        risk=args.sqlmap_risk,
    ))

    # Registra moduli interni
    orch.register("headers", InternalToolAdapter(HeadersModule()))
    orch.register("sensitive_files", InternalToolAdapter(SensitiveFilesModule()))

    # Solo check?
    if args.check:
        orch.check_tools()
        sys.exit(0)

    # Verifica e poi scansiona
    print()
    installed, missing = orch.check_tools()

    if not installed and missing:
        print("  Nessun tool installato! Lancia ./install_tools.sh")
        sys.exit(1)

    try:
        result = orch.run()
    except KeyboardInterrupt:
        print("\n\n  Scansione interrotta dall'utente.")
        sys.exit(1)

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
