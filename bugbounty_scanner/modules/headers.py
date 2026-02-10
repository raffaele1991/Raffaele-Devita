"""Security headers analysis module."""

import logging

import requests

from bugbounty_scanner.config import (
    DEFAULT_TIMEOUT,
    DEFAULT_USER_AGENT,
    SECURITY_HEADERS,
    SEVERITY_LOW,
    SEVERITY_MEDIUM,
    SEVERITY_INFO,
)
from bugbounty_scanner.scanner import Finding

logger = logging.getLogger("bugbounty_scanner")


class HeadersModule:
    """Checks for missing or misconfigured security headers."""

    name = "headers"

    def __init__(self):
        self.session = requests.Session()
        self.session.headers["User-Agent"] = DEFAULT_USER_AGENT
        self.session.verify = False

    def run(self, target, scan_result):
        findings = []
        try:
            resp = self.session.get(target, timeout=DEFAULT_TIMEOUT, allow_redirects=True)
        except requests.RequestException as e:
            logger.warning(f"  Headers module request failed: {e}")
            return findings

        headers = resp.headers

        # Check missing security headers
        critical_headers = {
            "Strict-Transport-Security": {
                "severity": SEVERITY_MEDIUM,
                "cwe": "CWE-319",
                "desc": "HSTS header is missing. The site may be vulnerable to protocol downgrade attacks.",
                "fix": "Add 'Strict-Transport-Security: max-age=31536000; includeSubDomains' header.",
            },
            "Content-Security-Policy": {
                "severity": SEVERITY_MEDIUM,
                "cwe": "CWE-79",
                "desc": "CSP header is missing. The site has no defense-in-depth against XSS attacks.",
                "fix": "Implement a Content-Security-Policy header with appropriate directives.",
            },
            "X-Content-Type-Options": {
                "severity": SEVERITY_LOW,
                "cwe": "CWE-16",
                "desc": "X-Content-Type-Options header is missing. Browser MIME sniffing is not prevented.",
                "fix": "Add 'X-Content-Type-Options: nosniff' header.",
            },
            "X-Frame-Options": {
                "severity": SEVERITY_MEDIUM,
                "cwe": "CWE-1021",
                "desc": "X-Frame-Options header is missing. The site may be vulnerable to clickjacking.",
                "fix": "Add 'X-Frame-Options: DENY' or 'SAMEORIGIN' header.",
            },
            "Referrer-Policy": {
                "severity": SEVERITY_LOW,
                "cwe": "CWE-200",
                "desc": "Referrer-Policy header is missing. Sensitive URL info may leak via Referer header.",
                "fix": "Add 'Referrer-Policy: strict-origin-when-cross-origin' header.",
            },
            "Permissions-Policy": {
                "severity": SEVERITY_LOW,
                "cwe": "CWE-16",
                "desc": "Permissions-Policy header is missing. Browser features are not restricted.",
                "fix": "Add a Permissions-Policy header to control browser feature access.",
            },
        }

        for header_name, info in critical_headers.items():
            if header_name not in headers:
                findings.append(Finding(
                    title=f"Missing Security Header: {header_name}",
                    severity=info["severity"],
                    url=target,
                    description=info["desc"],
                    evidence=f"Header '{header_name}' not found in response.",
                    remediation=info["fix"],
                    module=self.name,
                    cwe=info["cwe"],
                ))

        # Check for insecure CSP directives
        csp = headers.get("Content-Security-Policy", "")
        if csp:
            dangerous_directives = ["'unsafe-inline'", "'unsafe-eval'", "data:", "*"]
            for d in dangerous_directives:
                if d in csp:
                    findings.append(Finding(
                        title=f"Weak CSP Directive: {d}",
                        severity=SEVERITY_MEDIUM,
                        url=target,
                        description=f"The CSP header contains '{d}' which weakens the policy.",
                        evidence=f"CSP: {csp[:200]}",
                        remediation=f"Remove '{d}' from the Content-Security-Policy and use nonces/hashes.",
                        module=self.name,
                        cwe="CWE-79",
                    ))

        # Check for CORS misconfiguration
        acao = headers.get("Access-Control-Allow-Origin", "")
        if acao == "*":
            findings.append(Finding(
                title="Permissive CORS Policy",
                severity=SEVERITY_MEDIUM,
                url=target,
                description="Access-Control-Allow-Origin is set to '*', allowing any origin.",
                evidence=f"Access-Control-Allow-Origin: {acao}",
                remediation="Restrict CORS to trusted origins instead of using wildcard.",
                module=self.name,
                cwe="CWE-942",
            ))

        # Check ACAO reflects arbitrary origin
        try:
            evil_resp = self.session.get(
                target,
                headers={"Origin": "https://evil.com"},
                timeout=DEFAULT_TIMEOUT,
            )
            reflected_origin = evil_resp.headers.get("Access-Control-Allow-Origin", "")
            if "evil.com" in reflected_origin:
                acac = evil_resp.headers.get("Access-Control-Allow-Credentials", "")
                sev = SEVERITY_MEDIUM
                desc = "CORS reflects arbitrary origin."
                if acac.lower() == "true":
                    sev = "HIGH"
                    desc = "CORS reflects arbitrary origin WITH credentials. Sensitive data may be stolen cross-origin."
                findings.append(Finding(
                    title="CORS Origin Reflection",
                    severity=sev,
                    url=target,
                    description=desc,
                    evidence=f"Origin 'https://evil.com' reflected: {reflected_origin}",
                    remediation="Validate allowed origins against a strict whitelist.",
                    module=self.name,
                    cwe="CWE-942",
                ))
        except requests.RequestException:
            pass

        # Check cookies for security flags
        for cookie in resp.cookies:
            issues = []
            if not cookie.secure:
                issues.append("Secure flag missing")
            if "httponly" not in str(cookie).lower():
                issues.append("HttpOnly flag missing")
            samesite = cookie.get_nonstandard_attr("SameSite")
            if not samesite or samesite.lower() == "none":
                issues.append("SameSite not set or set to None")

            if issues:
                findings.append(Finding(
                    title=f"Insecure Cookie: {cookie.name}",
                    severity=SEVERITY_LOW,
                    url=target,
                    description=f"Cookie '{cookie.name}' is missing security attributes.",
                    evidence="; ".join(issues),
                    remediation="Set Secure, HttpOnly, and SameSite=Strict/Lax on all cookies.",
                    module=self.name,
                    cwe="CWE-614",
                ))

        return findings
