"""SQL Injection detection module."""

import logging
import re
import time
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

import requests

from bugbounty_scanner.config import (
    DEFAULT_TIMEOUT,
    DEFAULT_USER_AGENT,
    SQLI_PAYLOADS,
    SQL_ERROR_PATTERNS,
    SEVERITY_CRITICAL,
    SEVERITY_HIGH,
)
from bugbounty_scanner.scanner import Finding

logger = logging.getLogger("bugbounty_scanner")


class SQLiModule:
    """Detects SQL injection vulnerabilities (error-based, boolean-based, time-based)."""

    name = "sqli"

    def __init__(self):
        self.session = requests.Session()
        self.session.headers["User-Agent"] = DEFAULT_USER_AGENT
        self.session.verify = False

    def run(self, target, scan_result):
        findings = []
        parsed = urlparse(target)
        params = parse_qs(parsed.query, keep_blank_values=True)

        if not params:
            logger.info("  [SQLi] No URL parameters to test")
            return findings

        for param_name in params:
            # Error-based SQLi
            err_findings = self._test_error_based(target, param_name)
            findings.extend(err_findings)

            # Boolean-based blind SQLi
            bool_findings = self._test_boolean_based(target, param_name)
            findings.extend(bool_findings)

            # Time-based blind SQLi
            time_findings = self._test_time_based(target, param_name)
            findings.extend(time_findings)

        return findings

    def _build_url(self, target, param_name, payload):
        """Build a URL with the payload injected into the given parameter."""
        parsed = urlparse(target)
        base_params = parse_qs(parsed.query, keep_blank_values=True)
        test_params = {k: v[0] if isinstance(v, list) else v for k, v in base_params.items()}
        test_params[param_name] = payload

        return urlunparse((
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            parsed.params,
            urlencode(test_params),
            parsed.fragment,
        ))

    def _test_error_based(self, target, param_name):
        """Test for error-based SQL injection by looking for SQL error messages."""
        findings = []

        for payload in SQLI_PAYLOADS[:6]:  # Use the simpler payloads for error-based
            test_url = self._build_url(target, param_name, payload)
            try:
                resp = self.session.get(test_url, timeout=DEFAULT_TIMEOUT)
                body = resp.text.lower()

                for pattern in SQL_ERROR_PATTERNS:
                    if re.search(pattern, body, re.IGNORECASE):
                        findings.append(Finding(
                            title=f"SQL Injection (Error-Based) in '{param_name}'",
                            severity=SEVERITY_CRITICAL,
                            url=test_url,
                            description=(
                                f"Parameter '{param_name}' is vulnerable to error-based SQL injection. "
                                f"SQL error messages are visible in the response."
                            ),
                            evidence=f"Payload: {payload}\nError pattern matched: {pattern}",
                            remediation=(
                                "Use parameterized queries/prepared statements. "
                                "Never concatenate user input into SQL queries. "
                                "Disable detailed error messages in production."
                            ),
                            module=self.name,
                            cwe="CWE-89",
                        ))
                        return findings  # One confirmed finding is enough

            except requests.RequestException:
                continue

        return findings

    def _test_boolean_based(self, target, param_name):
        """Test for boolean-based blind SQL injection by comparing true/false responses."""
        findings = []

        try:
            # Get baseline response
            baseline_url = self._build_url(target, param_name, "1")
            baseline_resp = self.session.get(baseline_url, timeout=DEFAULT_TIMEOUT)
            baseline_len = len(baseline_resp.text)

            # True condition
            true_url = self._build_url(target, param_name, "1' AND '1'='1")
            true_resp = self.session.get(true_url, timeout=DEFAULT_TIMEOUT)
            true_len = len(true_resp.text)

            # False condition
            false_url = self._build_url(target, param_name, "1' AND '1'='2")
            false_resp = self.session.get(false_url, timeout=DEFAULT_TIMEOUT)
            false_len = len(false_resp.text)

            # If true response is similar to baseline but false is different
            true_diff = abs(true_len - baseline_len)
            false_diff = abs(false_len - baseline_len)

            if true_diff < 50 and false_diff > 200:
                findings.append(Finding(
                    title=f"SQL Injection (Boolean-Based Blind) in '{param_name}'",
                    severity=SEVERITY_HIGH,
                    url=target,
                    description=(
                        f"Parameter '{param_name}' appears vulnerable to boolean-based blind "
                        f"SQL injection. True and false conditions produce different responses."
                    ),
                    evidence=(
                        f"Baseline length: {baseline_len}\n"
                        f"True condition length: {true_len}\n"
                        f"False condition length: {false_len}"
                    ),
                    remediation="Use parameterized queries/prepared statements.",
                    module=self.name,
                    cwe="CWE-89",
                ))

        except requests.RequestException:
            pass

        return findings

    def _test_time_based(self, target, param_name):
        """Test for time-based blind SQL injection using SLEEP/WAITFOR."""
        findings = []
        time_payloads = [
            ("1' AND SLEEP(5)--", 5),
            ("1; WAITFOR DELAY '0:0:5'--", 5),
            ("1' OR SLEEP(5)--", 5),
        ]

        for payload, expected_delay in time_payloads:
            test_url = self._build_url(target, param_name, payload)
            try:
                start = time.time()
                self.session.get(test_url, timeout=DEFAULT_TIMEOUT + expected_delay + 2)
                elapsed = time.time() - start

                if elapsed >= expected_delay - 1:
                    # Verify with a second request to reduce false positives
                    start2 = time.time()
                    no_delay_url = self._build_url(target, param_name, "1")
                    self.session.get(no_delay_url, timeout=DEFAULT_TIMEOUT)
                    elapsed2 = time.time() - start2

                    if elapsed - elapsed2 >= expected_delay - 2:
                        findings.append(Finding(
                            title=f"SQL Injection (Time-Based Blind) in '{param_name}'",
                            severity=SEVERITY_HIGH,
                            url=test_url,
                            description=(
                                f"Parameter '{param_name}' is vulnerable to time-based blind "
                                f"SQL injection. Injected SLEEP caused {elapsed:.1f}s delay."
                            ),
                            evidence=(
                                f"Payload: {payload}\n"
                                f"Delayed response: {elapsed:.1f}s\n"
                                f"Normal response: {elapsed2:.1f}s"
                            ),
                            remediation="Use parameterized queries/prepared statements.",
                            module=self.name,
                            cwe="CWE-89",
                        ))
                        return findings

            except requests.RequestException:
                continue

        return findings
