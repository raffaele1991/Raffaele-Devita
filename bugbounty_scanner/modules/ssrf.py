"""Server-Side Request Forgery (SSRF) detection module."""

import logging
import re
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

import requests

from bugbounty_scanner.config import (
    DEFAULT_TIMEOUT,
    DEFAULT_USER_AGENT,
    SSRF_PAYLOADS,
    SEVERITY_HIGH,
    SEVERITY_CRITICAL,
)
from bugbounty_scanner.scanner import Finding

logger = logging.getLogger("bugbounty_scanner")


class SSRFModule:
    """Detects Server-Side Request Forgery vulnerabilities."""

    name = "ssrf"

    # Parameters commonly vulnerable to SSRF
    SSRF_PARAMS = [
        "url", "uri", "path", "dest", "redirect", "target", "rurl",
        "domain", "feed", "host", "site", "html", "data", "load",
        "file", "page", "proxy", "callback", "return", "next", "ref",
        "src", "href", "link", "image", "img", "fetch", "api",
    ]

    def __init__(self):
        self.session = requests.Session()
        self.session.headers["User-Agent"] = DEFAULT_USER_AGENT
        self.session.verify = False

    def run(self, target, scan_result):
        findings = []
        parsed = urlparse(target)
        params = parse_qs(parsed.query, keep_blank_values=True)

        # Test existing parameters that look SSRF-prone
        for param_name in params:
            if param_name.lower() in self.SSRF_PARAMS:
                ssrf_findings = self._test_ssrf(target, param_name)
                findings.extend(ssrf_findings)

        # Also try appending common SSRF params if not already present
        for ssrf_param in self.SSRF_PARAMS[:10]:
            if ssrf_param not in params:
                test_url = f"{target}{'&' if '?' in target else '?'}{ssrf_param}=https://example.com"
                ssrf_findings = self._test_ssrf(test_url, ssrf_param)
                findings.extend(ssrf_findings)

        return findings

    def _test_ssrf(self, target, param_name):
        """Test a parameter for SSRF by injecting internal URLs."""
        findings = []
        parsed = urlparse(target)

        for payload in SSRF_PAYLOADS:
            base_params = parse_qs(parsed.query, keep_blank_values=True)
            test_params = {k: v[0] if isinstance(v, list) else v for k, v in base_params.items()}
            test_params[param_name] = payload

            test_url = urlunparse((
                parsed.scheme,
                parsed.netloc,
                parsed.path,
                parsed.params,
                urlencode(test_params),
                parsed.fragment,
            ))

            try:
                resp = self.session.get(
                    test_url, timeout=DEFAULT_TIMEOUT, allow_redirects=False,
                )
                body = resp.text.lower()

                # Check for indicators of internal resource access
                indicators = self._check_ssrf_indicators(body, payload, resp)
                if indicators:
                    severity = SEVERITY_CRITICAL if "metadata" in payload else SEVERITY_HIGH
                    findings.append(Finding(
                        title=f"SSRF Detected in parameter '{param_name}'",
                        severity=severity,
                        url=test_url,
                        description=(
                            f"Parameter '{param_name}' may be vulnerable to Server-Side "
                            f"Request Forgery. The server fetched an internal resource."
                        ),
                        evidence=f"Payload: {payload}\nIndicators: {indicators}",
                        remediation=(
                            "Validate and whitelist allowed URLs/domains. "
                            "Block requests to internal/private IP ranges. "
                            "Use a URL parser to reject non-HTTP schemes."
                        ),
                        module=self.name,
                        cwe="CWE-918",
                    ))
                    return findings  # One confirmed finding per param

            except requests.RequestException:
                continue

        return findings

    def _check_ssrf_indicators(self, body, payload, response):
        """Check response for indicators that SSRF was successful."""
        indicators = []

        # Cloud metadata indicators
        if "169.254.169.254" in payload or "metadata" in payload:
            metadata_patterns = [
                "ami-id", "instance-id", "instance-type",
                "security-credentials", "iam",
                "computeMetadata", "project-id",
            ]
            for pat in metadata_patterns:
                if pat in body:
                    indicators.append(f"Cloud metadata pattern: {pat}")

        # Internal service indicators
        if any(x in payload for x in ["127.0.0.1", "localhost", "[::1]"]):
            internal_patterns = [
                "root:", "/home/", "daemon:",  # /etc/passwd
                "apache", "nginx", "server at",  # default pages
                "welcome to", "it works",
                "phpmyadmin", "dashboard",
            ]
            for pat in internal_patterns:
                if pat in body:
                    indicators.append(f"Internal content pattern: {pat}")

        # Status code based detection
        if response.status_code == 200 and len(body) > 0:
            if "127.0.0.1" in payload or "localhost" in payload:
                # Check if the response differs significantly from a normal error
                if not any(err in body for err in ["not found", "error", "invalid", "bad request"]):
                    if len(body) > 500:
                        indicators.append(f"Large response ({len(body)} chars) from internal URL")

        return "; ".join(indicators) if indicators else ""
