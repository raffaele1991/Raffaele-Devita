"""
Wayback Machine Module.

Cerca endpoint e parametri storici nell'archivio web (Wayback Machine).
Spesso vecchi endpoint rimossi dal sito sono ancora funzionanti.
"""

import logging
import re
from urllib.parse import urlparse, parse_qs

from bugbounty_scanner.config import SEVERITY_INFO, SEVERITY_LOW
from bugbounty_scanner.scanner import Finding

logger = logging.getLogger("bugbounty_scanner")

WAYBACK_API = "https://web.archive.org/cdx/search/cdx"


class WaybackModule:
    """Cerca vecchi endpoint e parametri dalla Wayback Machine."""

    name = "wayback"

    def __init__(self, http_session=None, max_results=1000):
        if http_session:
            self.session = http_session
        else:
            from bugbounty_scanner.http_session import HttpSession
            self.session = HttpSession()
        self.max_results = max_results

    def run(self, target, scan_result):
        findings = []
        parsed = urlparse(target)
        domain = parsed.netloc

        logger.info(f"  [Wayback] Cercando URL storici per {domain}")

        # Query Wayback Machine CDX API
        urls = self._fetch_wayback_urls(domain)

        if not urls:
            logger.info("  [Wayback] Nessun URL storico trovato")
            return findings

        logger.info(f"  [Wayback] Trovati {len(urls)} URL storici")

        # Analizza gli URL trovati
        endpoints = set()
        params = set()
        interesting_paths = set()
        old_files = set()

        interesting_extensions = [
            ".sql", ".bak", ".backup", ".old", ".orig", ".conf", ".config",
            ".env", ".log", ".xml", ".json", ".yaml", ".yml", ".csv",
            ".xls", ".xlsx", ".doc", ".pdf", ".zip", ".tar", ".gz",
            ".rar", ".7z", ".swp", ".DS_Store", ".git",
        ]

        interesting_path_keywords = [
            "admin", "dashboard", "panel", "internal", "debug", "test",
            "staging", "dev", "api", "graphql", "upload", "export",
            "backup", "config", "setup", "install", "phpinfo",
            "phpmyadmin", "console", "actuator", "swagger", "docs",
        ]

        for url in urls:
            try:
                parsed_url = urlparse(url)
                path = parsed_url.path.lower()

                # Raccogli tutti gli endpoint unici
                if parsed_url.path and parsed_url.path != "/":
                    endpoints.add(parsed_url.path)

                # Raccogli parametri
                for param_name in parse_qs(parsed_url.query):
                    params.add(param_name)

                # Cerca path interessanti
                for keyword in interesting_path_keywords:
                    if keyword in path:
                        interesting_paths.add(parsed_url.path)

                # Cerca file con estensioni interessanti
                for ext in interesting_extensions:
                    if path.endswith(ext):
                        old_files.add(url)

            except Exception:
                continue

        # Genera finding per endpoint storici
        if endpoints:
            findings.append(Finding(
                title=f"Endpoint storici dalla Wayback Machine ({len(endpoints)})",
                severity=SEVERITY_INFO,
                url=target,
                description=(
                    f"La Wayback Machine ha archiviato {len(endpoints)} endpoint unici. "
                    f"Alcuni potrebbero essere ancora attivi o esporre informazioni."
                ),
                evidence="\n".join(sorted(endpoints)[:40]),
                module=self.name,
            ))

        if params:
            findings.append(Finding(
                title=f"Parametri storici scoperti ({len(params)})",
                severity=SEVERITY_INFO,
                url=target,
                description=(
                    f"Trovati {len(params)} parametri query string unici negli archivi. "
                    f"Utili per testare XSS, SQLi, SSRF."
                ),
                evidence=", ".join(sorted(params)[:50]),
                module=self.name,
            ))

        if interesting_paths:
            findings.append(Finding(
                title=f"Path sensibili nell'archivio ({len(interesting_paths)})",
                severity=SEVERITY_LOW,
                url=target,
                description="Path potenzialmente interessanti trovati nella Wayback Machine.",
                evidence="\n".join(sorted(interesting_paths)[:20]),
                remediation="Verifica che questi path non siano ancora accessibili.",
                module=self.name,
            ))

        if old_files:
            findings.append(Finding(
                title=f"File sensibili nell'archivio ({len(old_files)})",
                severity=SEVERITY_LOW,
                url=target,
                description="File con estensioni sensibili trovati nella Wayback Machine.",
                evidence="\n".join(sorted(old_files)[:20]),
                remediation="Verifica che questi file non siano ancora accessibili o contengano dati sensibili.",
                module=self.name,
            ))

        # Salva nel scan_result per gli altri moduli
        scan_result.wayback_endpoints = list(endpoints)
        scan_result.wayback_params = list(params)

        return findings

    def _fetch_wayback_urls(self, domain):
        """Interroga la Wayback Machine CDX API."""
        urls = set()

        params = {
            "url": f"*.{domain}/*",
            "output": "text",
            "fl": "original",
            "collapse": "urlkey",
            "limit": str(self.max_results),
            "filter": "statuscode:200",
        }

        try:
            resp = self.session.get(WAYBACK_API, params=params, timeout=30)
            if resp.status_code == 200:
                for line in resp.text.splitlines():
                    line = line.strip()
                    if line and line.startswith("http"):
                        urls.add(line)
        except Exception as e:
            logger.warning(f"  [Wayback] Errore API: {e}")

        return list(urls)
