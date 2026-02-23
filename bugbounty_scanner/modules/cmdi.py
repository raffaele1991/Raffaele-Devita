"""Command Injection / OS Injection detection module."""

import logging
import re
import time
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

import requests
from bs4 import BeautifulSoup

from bugbounty_scanner.config import (
    DEFAULT_TIMEOUT,
    CMDI_PAYLOADS,
    CMDI_PATTERNS,
    SEVERITY_CRITICAL,
    SEVERITY_HIGH,
)
from bugbounty_scanner.scanner import Finding

logger = logging.getLogger("bugbounty_scanner")


class CMDIModule:
    """Detects OS Command Injection vulnerabilities (error-based and time-based)."""

    name = "cmdi"

    # Parameters likely used in OS-level operations
    RISKY_PARAMS = [
        "cmd", "exec", "command", "execute", "ping", "query", "jump",
        "code", "reg", "do", "func", "arg", "option", "load", "process",
        "step", "read", "function", "req", "feature", "exe", "module",
        "payload", "run", "print", "file", "ip", "host", "target",
        "path", "dir", "name", "input", "data",
    ]

    def __init__(self, http_session=None):
        if http_session:
            self.session = http_session
        else:
            from bugbounty_scanner.http_session import HttpSession
            self.session = HttpSession()

    def run(self, target, scan_result):
        findings = []
        parsed = urlparse(target)
        params = parse_qs(parsed.query, keep_blank_values=True)

        # Test URL parameters
        for param_name in params:
            findings.extend(self._test_error_based(target, param_name))
            findings.extend(self._test_time_based(target, param_name))

        # Test form inputs discovered by crawler (if available)
        discovered_forms = getattr(scan_result, "discovered_forms", [])
        for form in discovered_forms:
            for field_name in form.get("fields", []):
                form_url = form.get("action", target)
                if form.get("method", "GET").upper() == "POST":
                    findings.extend(self._test_post_cmdi(form_url, field_name))
                else:
                    findings.extend(self._test_error_based(form_url, field_name))
                    findings.extend(self._test_time_based(form_url, field_name))

        # Also test risky-named params even if not in URL (via GET fuzzing)
        discovered_params = getattr(scan_result, "discovered_params", [])
        tested = set(params.keys())
        for param_info in discovered_params:
            # param_info format: "param_name (url)"
            parts = param_info.split(" (")
            if not parts:
                continue
            pname = parts[0].strip()
            if pname not in tested and pname.lower() in self.RISKY_PARAMS:
                tested.add(pname)
                findings.extend(self._test_error_based(target, pname))
                findings.extend(self._test_time_based(target, pname))

        if not params and not discovered_forms:
            logger.info("  [CMDi] Nessun parametro da testare")

        return findings

    def _build_url(self, target, param_name, payload):
        parsed = urlparse(target)
        base_params = parse_qs(parsed.query, keep_blank_values=True)
        test_params = {k: v[0] if isinstance(v, list) else v for k, v in base_params.items()}
        test_params[param_name] = payload
        return urlunparse((
            parsed.scheme, parsed.netloc, parsed.path,
            parsed.params, urlencode(test_params), parsed.fragment,
        ))

    def _test_error_based(self, target, param_name):
        """Test for command injection via error patterns in response."""
        findings = []
        for payload in CMDI_PAYLOADS:
            test_url = self._build_url(target, param_name, payload)
            try:
                resp = self.session.get(test_url, timeout=DEFAULT_TIMEOUT, allow_redirects=True)
                body = resp.text

                for pattern, description in CMDI_PATTERNS:
                    if re.search(pattern, body, re.IGNORECASE):
                        findings.append(Finding(
                            title=f"OS Command Injection in '{param_name}'",
                            severity=SEVERITY_CRITICAL,
                            url=test_url,
                            description=(
                                f"Il parametro '{param_name}' è vulnerabile a OS Command Injection. "
                                f"L'output del comando di sistema è visibile nella risposta ({description})."
                            ),
                            evidence=f"Payload: {payload}\nPattern trovato: {pattern}",
                            remediation=(
                                "Non passare mai input utente a funzioni shell (system(), exec(), popen()). "
                                "Usa API native del linguaggio. Se necessario, validare con whitelist stretta."
                            ),
                            module=self.name,
                            cwe="CWE-78",
                        ))
                        return findings  # Trovato, basta un finding per param

            except requests.RequestException:
                continue

        return findings

    def _test_time_based(self, target, param_name):
        """Detect blind command injection via response time delay."""
        findings = []

        # Time-based payloads: sleep 5 seconds
        time_payloads = [
            "; sleep 5",
            "| sleep 5",
            "` sleep 5`",
            "$(sleep 5)",
            "; ping -c 5 127.0.0.1",
            "& timeout /T 5",         # Windows
            "| timeout /T 5",         # Windows
        ]

        try:
            # Baseline timing
            baseline_url = self._build_url(target, param_name, "1")
            t0 = time.time()
            self.session.get(baseline_url, timeout=DEFAULT_TIMEOUT)
            baseline_duration = time.time() - t0
        except requests.RequestException:
            return findings

        for payload in time_payloads:
            test_url = self._build_url(target, param_name, payload)
            try:
                t_start = time.time()
                self.session.get(test_url, timeout=DEFAULT_TIMEOUT + 10)
                elapsed = time.time() - t_start

                if elapsed >= (baseline_duration + 4.5):
                    findings.append(Finding(
                        title=f"Blind OS Command Injection (Time-Based) in '{param_name}'",
                        severity=SEVERITY_CRITICAL,
                        url=test_url,
                        description=(
                            f"Il parametro '{param_name}' è vulnerabile a Blind Command Injection. "
                            f"Il payload ha causato un ritardo di {elapsed:.1f}s (baseline: {baseline_duration:.1f}s)."
                        ),
                        evidence=f"Payload: {payload}\nBaseline: {baseline_duration:.2f}s, Con payload: {elapsed:.2f}s",
                        remediation=(
                            "Evitare l'esecuzione di comandi shell con input utente. "
                            "Usare librerie native del linguaggio per le operazioni di sistema."
                        ),
                        module=self.name,
                        cwe="CWE-78",
                    ))
                    return findings  # Un finding per param è sufficiente

            except requests.RequestException:
                continue

        return findings

    def _test_post_cmdi(self, url, field_name):
        """Test command injection via POST form fields."""
        findings = []
        for payload in CMDI_PAYLOADS:
            try:
                resp = self.session.post(
                    url,
                    data={field_name: payload},
                    timeout=DEFAULT_TIMEOUT,
                    allow_redirects=True,
                )
                body = resp.text
                for pattern, description in CMDI_PATTERNS:
                    if re.search(pattern, body, re.IGNORECASE):
                        findings.append(Finding(
                            title=f"OS Command Injection (POST) in campo '{field_name}'",
                            severity=SEVERITY_CRITICAL,
                            url=url,
                            description=(
                                f"Il campo POST '{field_name}' è vulnerabile a OS Command Injection. "
                                f"Output di sistema visibile nella risposta ({description})."
                            ),
                            evidence=f"Field: {field_name}\nPayload: {payload}\nPattern: {pattern}",
                            remediation="Validare e sanificare tutti gli input prima di passarli a funzioni di sistema.",
                            module=self.name,
                            cwe="CWE-78",
                        ))
                        return findings
            except requests.RequestException:
                continue
        return findings
