"""Open Redirect detection module."""

import logging
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

import requests

from bugbounty_scanner.config import (
    DEFAULT_TIMEOUT,
    DEFAULT_USER_AGENT,
    OPEN_REDIRECT_PAYLOADS,
    SEVERITY_MEDIUM,
)
from bugbounty_scanner.scanner import Finding

logger = logging.getLogger("bugbounty_scanner")


class OpenRedirectModule:
    """Detects open redirect vulnerabilities."""

    name = "open_redirect"

    REDIRECT_PARAMS = [
        "url", "redirect", "redirect_url", "redirect_uri", "return",
        "return_url", "returnTo", "rurl", "next", "dest", "destination",
        "redir", "redirect_to", "target", "view", "login_url",
        "continue", "goto", "checkout_url", "forward", "out",
    ]

    def __init__(self):
        self.session = requests.Session()
        self.session.headers["User-Agent"] = DEFAULT_USER_AGENT
        self.session.verify = False

    def run(self, target, scan_result):
        findings = []
        parsed = urlparse(target)
        params = parse_qs(parsed.query, keep_blank_values=True)

        # Test existing redirect-like parameters
        for param_name in params:
            if param_name.lower() in self.REDIRECT_PARAMS:
                redir_findings = self._test_redirect(target, param_name)
                findings.extend(redir_findings)

        # Try common redirect parameter names
        for redir_param in self.REDIRECT_PARAMS[:10]:
            if redir_param not in params:
                test_url = f"{target}{'&' if '?' in target else '?'}{redir_param}=https://example.com"
                redir_findings = self._test_redirect(test_url, redir_param)
                findings.extend(redir_findings)

        return findings

    def _test_redirect(self, target, param_name):
        """Test a parameter for open redirect by injecting external URLs."""
        findings = []
        parsed = urlparse(target)

        for payload in OPEN_REDIRECT_PAYLOADS:
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

                # Check for redirect to external domain
                if resp.status_code in (301, 302, 303, 307, 308):
                    location = resp.headers.get("Location", "")
                    if self._is_external_redirect(location, parsed.netloc):
                        findings.append(Finding(
                            title=f"Open Redirect in parameter '{param_name}'",
                            severity=SEVERITY_MEDIUM,
                            url=test_url,
                            description=(
                                f"Parameter '{param_name}' allows redirecting users to external sites. "
                                f"This can be used for phishing attacks."
                            ),
                            evidence=f"Payload: {payload}\nRedirects to: {location}",
                            remediation=(
                                "Validate redirect URLs against a whitelist of allowed domains. "
                                "Use relative paths for redirects when possible."
                            ),
                            module=self.name,
                            cwe="CWE-601",
                        ))
                        return findings

                # Check for meta refresh or JavaScript redirect
                if resp.status_code == 200:
                    body = resp.text.lower()
                    if "evil.com" in body and (
                        "meta http-equiv" in body or "window.location" in body
                    ):
                        findings.append(Finding(
                            title=f"Open Redirect (DOM/Meta) in parameter '{param_name}'",
                            severity=SEVERITY_MEDIUM,
                            url=test_url,
                            description=(
                                f"Parameter '{param_name}' causes a client-side redirect to an external site."
                            ),
                            evidence=f"Payload: {payload}\nReflected in page causing redirect",
                            remediation="Validate redirect targets server-side.",
                            module=self.name,
                            cwe="CWE-601",
                        ))
                        return findings

            except requests.RequestException:
                continue

        return findings

    @staticmethod
    def _is_external_redirect(location, original_host):
        """Check if a Location header points to an external domain."""
        if not location:
            return False
        if location.startswith("//"):
            return True
        try:
            loc_parsed = urlparse(location)
            if loc_parsed.netloc and loc_parsed.netloc != original_host:
                return True
        except Exception:
            pass
        return False
