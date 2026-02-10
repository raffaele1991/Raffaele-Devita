"""Sensitive file and directory discovery module."""

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

from bugbounty_scanner.config import (
    DEFAULT_TIMEOUT,
    DEFAULT_USER_AGENT,
    SENSITIVE_PATHS,
    SEVERITY_HIGH,
    SEVERITY_MEDIUM,
    SEVERITY_LOW,
    SEVERITY_INFO,
)
from bugbounty_scanner.scanner import Finding

logger = logging.getLogger("bugbounty_scanner")


class SensitiveFilesModule:
    """Discovers exposed sensitive files, directories, and endpoints."""

    name = "sensitive_files"

    # Paths that are critical if found
    CRITICAL_PATHS = {
        "/.env", "/.git/config", "/.git/HEAD", "/.aws/credentials",
        "/backup.sql", "/dump.sql", "/database.sql",
    }

    HIGH_PATHS = {
        "/wp-config.php", "/config.php", "/configuration.php",
        "/.htpasswd", "/web.config", "/phpinfo.php",
        "/actuator/env", "/actuator",
        "/graphql", "/graphiql",
    }

    def __init__(self, threads=10, http_session=None):
        self.threads = threads
        if http_session:
            self.session = http_session
        else:
            from bugbounty_scanner.http_session import HttpSession
            self.session = HttpSession()

    def run(self, target, scan_result):
        findings = []
        logger.info(f"  [SensitiveFiles] Checking {len(SENSITIVE_PATHS)} paths")

        # Prima richiesta: prendi la baseline (pagina catch-all / 404 custom)
        baseline_len = self._get_baseline_length(target)

        def check_path(path):
            url = f"{target.rstrip('/')}{path}"
            try:
                resp = self.session.get(
                    url, timeout=DEFAULT_TIMEOUT, allow_redirects=False,
                )
                if resp.status_code == 200 and len(resp.text) > 0:
                    # Filter out generic error/404 pages
                    if self._is_soft_404(resp):
                        return None
                    # Catch-all: stessa lunghezza della pagina di default
                    if baseline_len and abs(len(resp.text) - baseline_len) < 100:
                        return None
                    # Verifica che il contenuto sia coerente col tipo di file
                    if not self._content_matches_path(path, resp.text):
                        return None
                    return (path, url, resp)
            except requests.RequestException:
                pass
            return None

        with ThreadPoolExecutor(max_workers=self.threads) as pool:
            futures = {pool.submit(check_path, p): p for p in SENSITIVE_PATHS}
            for fut in as_completed(futures):
                result = fut.result()
                if result:
                    path, url, resp = result
                    severity = self._classify_severity(path)
                    findings.append(Finding(
                        title=f"Sensitive File Exposed: {path}",
                        severity=severity,
                        url=url,
                        description=f"The file/endpoint '{path}' is publicly accessible.",
                        evidence=(
                            f"HTTP {resp.status_code} - "
                            f"Content-Length: {len(resp.text)} bytes\n"
                            f"Preview: {resp.text[:200]}..."
                        ),
                        remediation=(
                            "Restrict access to this file/endpoint. "
                            "Use web server configuration to deny access to sensitive paths. "
                            "Remove unnecessary files from the web root."
                        ),
                        module=self.name,
                        cwe="CWE-538",
                    ))

        return findings

    def _classify_severity(self, path):
        """Determine severity based on the type of exposed file."""
        if path in self.CRITICAL_PATHS:
            return SEVERITY_HIGH
        if path in self.HIGH_PATHS:
            return SEVERITY_MEDIUM
        # Path generici (robots.txt, sitemap, ecc.) sono solo noise
        return SEVERITY_INFO

    def _get_baseline_length(self, target):
        """Richiedi un path che non esiste per ottenere la pagina catch-all."""
        try:
            resp = self.session.get(
                f"{target.rstrip('/')}/thispagedoesnotexist7391",
                timeout=DEFAULT_TIMEOUT,
                allow_redirects=False,
            )
            if resp.status_code == 200:
                return len(resp.text)
        except requests.RequestException:
            pass
        return None

    @staticmethod
    def _content_matches_path(path, content):
        """Verifica che il contenuto sia coerente col tipo di file atteso."""
        body = content.strip().lower()

        # Se il contenuto è HTML e il file non dovrebbe essere HTML → falso positivo
        is_html = body.startswith(("<!doctype", "<html", "<?xml"))

        # File che NON devono mai essere HTML
        non_html_files = {
            "/.env": lambda b: "=" in content and not is_html,
            "/.git/config": lambda b: "[core]" in b or "[remote" in b,
            "/.git/HEAD": lambda b: b.startswith("ref:") or len(b) == 40,
            "/.aws/credentials": lambda b: "[default]" in b or "aws_access" in b,
            "/backup.sql": lambda b: "create table" in b or "insert into" in b,
            "/dump.sql": lambda b: "create table" in b or "insert into" in b,
            "/database.sql": lambda b: "create table" in b or "insert into" in b,
            "/.htpasswd": lambda b: ":" in content and not is_html and len(content) < 5000,
            "/phpinfo.php": lambda b: "php version" in b or "phpinfo()" in b,
            "/wp-config.php": lambda b: "db_name" in b or "db_password" in b,
            "/config.php": lambda b: not is_html or "password" in b,
            "/web.config": lambda b: "configuration" in b and "<?xml" in b,
        }

        validator = non_html_files.get(path)
        if validator:
            return validator(body)

        # Per gli altri path: se è HTML generico, probabilmente è una SPA/catch-all
        # Accetta solo se contiene contenuto specifico del path
        if is_html and path not in ("/actuator", "/graphql", "/graphiql",
                                     "/admin", "/administrator", "/phpmyadmin"):
            return False

        return True

    @staticmethod
    def _is_soft_404(response):
        """Detect soft 404 pages that return 200 but are actually errors."""
        body = response.text.lower()
        soft_404_indicators = [
            "page not found",
            "404 not found",
            "not found",
            "does not exist",
            "no longer available",
            "error 404",
            "the page you",
        ]
        # If the page is very short AND contains error text, it's likely a soft 404
        if len(body) < 5000:
            for indicator in soft_404_indicators:
                if indicator in body:
                    return True
        return False
