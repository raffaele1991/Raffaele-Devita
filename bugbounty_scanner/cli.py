#!/usr/bin/env python3
"""Interfaccia CLI per il Bug Bounty Vulnerability Scanner."""

import argparse
import logging
import sys
import urllib3

from bugbounty_scanner.scanner import Scanner
from bugbounty_scanner.modules.recon import ReconModule
from bugbounty_scanner.modules.headers import HeadersModule
from bugbounty_scanner.modules.xss import XSSModule
from bugbounty_scanner.modules.sqli import SQLiModule
from bugbounty_scanner.modules.ssrf import SSRFModule
from bugbounty_scanner.modules.open_redirect import OpenRedirectModule
from bugbounty_scanner.modules.sensitive_files import SensitiveFilesModule
from bugbounty_scanner.reporter import Reporter

# Disabilita warning SSL per i test
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BANNER = r"""
  ____              ____                    _
 | __ ) _   _  __ _| __ )  ___  _   _ _ __ | |_ _   _
 |  _ \| | | |/ _` |  _ \ / _ \| | | | '_ \| __| | | |
 | |_) | |_| | (_| | |_) | (_) | |_| | | | | |_| |_| |
 |____/ \__,_|\__, |____/ \___/ \__,_|_| |_|\__|\__, |
              |___/                              |___/
      ____
     / ___|  ___ __ _ _ __  _ __   ___ _ __
     \___ \ / __/ _` | '_ \| '_ \ / _ \ '__|
      ___) | (_| (_| | | | | | | |  __/ |
     |____/ \___\__,_|_| |_|_| |_|\___|_|

     Bug Bounty Vulnerability Scanner Agent v1.0
"""

ALL_MODULES = ["recon", "headers", "xss", "sqli", "ssrf", "open_redirect", "sensitive_files"]


def parse_args():
    parser = argparse.ArgumentParser(
        description="Bug Bounty Vulnerability Scanner - Scansione automatica di vulnerabilita web",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Esempi di utilizzo:
  %(prog)s -t example.com                      Scansione completa
  %(prog)s -t example.com -m xss sqli          Solo moduli XSS e SQLi
  %(prog)s -t example.com --no-recon            Salta la ricognizione
  %(prog)s -t example.com -o report -f html     Report HTML nella cartella 'report'
  %(prog)s -t https://example.com/page?id=1     Scansione con parametri specifici
        """,
    )

    parser.add_argument(
        "-t", "--target",
        required=True,
        help="URL o dominio target (es: example.com o https://example.com/path?param=value)",
    )
    parser.add_argument(
        "-m", "--modules",
        nargs="+",
        choices=ALL_MODULES,
        default=None,
        help=f"Moduli da eseguire (default: tutti). Opzioni: {', '.join(ALL_MODULES)}",
    )
    parser.add_argument(
        "--no-recon",
        action="store_true",
        help="Salta il modulo di ricognizione (subdomain, porte, tech detection)",
    )
    parser.add_argument(
        "--threads",
        type=int,
        default=10,
        help="Numero di thread per le operazioni parallele (default: 10)",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.5,
        help="Ritardo in secondi tra le richieste dei moduli (default: 0.5)",
    )
    parser.add_argument(
        "-o", "--output-dir",
        default="reports",
        help="Cartella per i report (default: reports)",
    )
    parser.add_argument(
        "-f", "--format",
        nargs="+",
        choices=["json", "html", "markdown", "all"],
        default=["all"],
        help="Formato del report (default: all)",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Output dettagliato (debug logging)",
    )
    parser.add_argument(
        "-q", "--quiet",
        action="store_true",
        help="Output minimo (solo errori)",
    )

    return parser.parse_args()


def setup_logging(verbose=False, quiet=False):
    level = logging.DEBUG if verbose else (logging.ERROR if quiet else logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )


def main():
    args = parse_args()
    setup_logging(verbose=args.verbose, quiet=args.quiet)
    logger = logging.getLogger("bugbounty_scanner")

    if not args.quiet:
        print(BANNER)

    # Determina i moduli da eseguire
    enabled = args.modules
    if args.no_recon:
        if enabled is None:
            enabled = [m for m in ALL_MODULES if m != "recon"]
        elif "recon" in enabled:
            enabled.remove("recon")

    # Crea lo scanner
    scanner = Scanner(
        target=args.target,
        threads=args.threads,
        delay=args.delay,
        modules=enabled,
        verbose=args.verbose,
    )

    # Registra i moduli
    scanner.register_module(ReconModule(threads=args.threads))
    scanner.register_module(HeadersModule())
    scanner.register_module(XSSModule())
    scanner.register_module(SQLiModule())
    scanner.register_module(SSRFModule())
    scanner.register_module(OpenRedirectModule())
    scanner.register_module(SensitiveFilesModule(threads=args.threads))

    # Esegui la scansione
    logger.info(f"Target: {scanner.target}")
    logger.info(f"Moduli: {enabled or 'tutti'}")
    logger.info(f"Thread: {args.threads}")
    print()

    try:
        result = scanner.run()
    except KeyboardInterrupt:
        print("\n\nScansione interrotta dall'utente.")
        sys.exit(1)

    # Genera i report
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

    # Exit code basato sulla gravita
    severity_counts = result.summary["by_severity"]
    if severity_counts.get("CRITICAL", 0) > 0 or severity_counts.get("HIGH", 0) > 0:
        sys.exit(2)  # Vulnerabilita critiche/alte trovate
    elif severity_counts.get("MEDIUM", 0) > 0:
        sys.exit(1)  # Vulnerabilita medie trovate
    sys.exit(0)


if __name__ == "__main__":
    main()
