#!/usr/bin/env python3
"""Interfaccia CLI per il Bug Bounty Vulnerability Scanner."""

import argparse
import logging
import sys
import urllib3

from bugbounty_scanner.license_manager import check_license
from bugbounty_scanner.scanner import Scanner
from bugbounty_scanner.modules.recon import ReconModule
from bugbounty_scanner.modules.headers import HeadersModule
from bugbounty_scanner.modules.xss import XSSModule
from bugbounty_scanner.modules.sqli import SQLiModule
from bugbounty_scanner.modules.ssrf import SSRFModule
from bugbounty_scanner.modules.open_redirect import OpenRedirectModule
from bugbounty_scanner.modules.sensitive_files import SensitiveFilesModule
from bugbounty_scanner.modules.crawler import CrawlerModule
from bugbounty_scanner.modules.cmdi import CMDIModule
from bugbounty_scanner.modules.rce import RCEModule
from bugbounty_scanner.modules.privesc import PrivEscModule
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

ALL_MODULES = [
    "recon", "crawler", "headers", "xss", "sqli", "ssrf",
    "open_redirect", "sensitive_files", "cmdi", "rce", "privesc",
]


def parse_args():
    parser = argparse.ArgumentParser(
        description="Bug Bounty Vulnerability Scanner - Scansione automatica di vulnerabilita web",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Esempi di utilizzo:
  %(prog)s -t example.com                                            Scansione completa
  %(prog)s -t example.com -m xss sqli                                Solo moduli XSS e SQLi
  %(prog)s -t example.com --no-recon                                 Salta la ricognizione
  %(prog)s -t example.com -H "X-Bug-Bounty: kobraraf91"             Header custom
  %(prog)s -t example.com --email kobraraf91@intigriti.me            Con email identificativa
  %(prog)s -t example.com --rate-limit 5                             Max 5 req/sec
  %(prog)s -t example.com -H "X-Bug-Bounty: kobraraf91" --rate-limit 3  Combo completa
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
        "-H", "--header",
        action="append",
        metavar="'Nome: Valore'",
        help="Header HTTP custom (ripetibile). Es: -H 'X-Bug-Bounty: kobraraf91'",
    )
    parser.add_argument(
        "--email",
        default=None,
        help="Email identificativa per il programma bug bounty (aggiunta agli header)",
    )
    parser.add_argument(
        "--rate-limit",
        type=float,
        default=5,
        help="Massimo richieste al secondo (default: 5). Usa 0 per nessun limite.",
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

    # Verifica licenza (LITE e sufficiente)
    license_info = check_license(require_pro=False)
    logger.info(f"Licenza {license_info['plan']} attiva ({license_info['email']})")

    # Determina i moduli da eseguire
    enabled = args.modules
    if args.no_recon:
        if enabled is None:
            enabled = [m for m in ALL_MODULES if m != "recon"]
        elif "recon" in enabled:
            enabled.remove("recon")

    # Crea sessione HTTP condivisa con header custom e rate limiting
    from bugbounty_scanner.http_session import HttpSession, parse_headers_list

    custom_headers = parse_headers_list(args.header)
    http_session = HttpSession(
        headers=custom_headers,
        email=args.email,
        rate_limit=args.rate_limit,
    )

    # Mostra configurazione
    if custom_headers:
        for k, v in custom_headers.items():
            logger.info(f"Header custom: {k}: {v}")
    if args.email:
        logger.info(f"Email: {args.email}")
    logger.info(f"Rate limit: {args.rate_limit} req/sec")

    # Crea lo scanner
    scanner = Scanner(
        target=args.target,
        threads=args.threads,
        delay=args.delay,
        modules=enabled,
        verbose=args.verbose,
    )

    # Registra i moduli con la sessione condivisa
    # NOTA: CrawlerModule deve essere registrato prima dei moduli di attacco
    # perché popola scan_result.discovered_forms e scan_result.discovered_params
    # che vengono usati da CMDi, RCE, PrivEsc, XSS, SQLi, ecc.
    scanner.register_module(ReconModule(threads=args.threads, http_session=http_session))
    scanner.register_module(CrawlerModule(http_session=http_session, max_pages=100, max_depth=3))
    scanner.register_module(HeadersModule(http_session=http_session))
    scanner.register_module(XSSModule(http_session=http_session))
    scanner.register_module(SQLiModule(http_session=http_session))
    scanner.register_module(SSRFModule(http_session=http_session))
    scanner.register_module(OpenRedirectModule(http_session=http_session))
    scanner.register_module(SensitiveFilesModule(threads=args.threads, http_session=http_session))
    scanner.register_module(CMDIModule(http_session=http_session))
    scanner.register_module(RCEModule(http_session=http_session))
    scanner.register_module(PrivEscModule(http_session=http_session))

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
