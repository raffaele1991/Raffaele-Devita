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

        def check_path(path):
            url = f"{target.rstrip('/')}{path}"
            try:
                resp = self.session.get(
                    url, timeout=DEFAULT_TIMEOUT, allow_redirects=False,
                )
                if resp.status_code == 200 and len(resp.text) > 0:
                    # Filter out generic error/404 pages
                    if not self._is_soft_404(resp):
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
