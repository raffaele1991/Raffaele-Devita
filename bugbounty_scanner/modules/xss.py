"""Cross-Site Scripting (XSS) detection module."""

import logging
import re
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

import requests
from bs4 import BeautifulSoup

from bugbounty_scanner.config import (
    DEFAULT_TIMEOUT,
    DEFAULT_USER_AGENT,
    XSS_PAYLOADS,
    SEVERITY_HIGH,
    SEVERITY_MEDIUM,
    SEVERITY_INFO,
)
from bugbounty_scanner.scanner import Finding

logger = logging.getLogger("bugbounty_scanner")


class XSSModule:
    """Detects reflected and DOM-based XSS vulnerabilities."""

    name = "xss"

    def __init__(self, http_session=None):
        if http_session:
            self.session = http_session
        else:
            from bugbounty_scanner.http_session import HttpSession
            self.session = HttpSession()

    def run(self, target, scan_result):
        findings = []

        # 1. Discover input parameters by crawling the target
        params = self._discover_params(target)
        logger.info(f"  [XSS] Discovered {len(params)} parameter(s) to test")

        # 2. Test reflected XSS on each parameter
        for url, param_name in params:
            xss_findings = self._test_reflected_xss(url, param_name)
            findings.extend(xss_findings)

        # 3. Check for DOM-based XSS sinks
        dom_findings = self._check_dom_xss(target)
        findings.extend(dom_findings)

        return findings

    def _discover_params(self, target):
        """Find URLs with query parameters by parsing the page."""
        params = []
        parsed = urlparse(target)

        # Test existing URL parameters
        qs = parse_qs(parsed.query)
        for param_name in qs:
            params.append((target, param_name))

        # Crawl the page for forms and links
        try:
            resp = self.session.get(target, timeout=DEFAULT_TIMEOUT)
            soup = BeautifulSoup(resp.text, "html.parser")

            # Find forms
            for form in soup.find_all("form"):
                action = form.get("action", "")
                if action and not action.startswith(("http://", "https://")):
                    action = f"{parsed.scheme}://{parsed.netloc}{action}"
                elif not action:
                    action = target

                for inp in form.find_all(["input", "textarea"]):
                    name = inp.get("name")
                    if name:
                        params.append((action, name))

            # Find links with parameters
            for link in soup.find_all("a", href=True):
                href = link["href"]
                if "?" in href:
                    if not href.startswith(("http://", "https://")):
                        href = f"{parsed.scheme}://{parsed.netloc}{href}"
                    link_parsed = urlparse(href)
                    if link_parsed.netloc == parsed.netloc:
                        for p in parse_qs(link_parsed.query):
                            params.append((href, p))

        except requests.RequestException as e:
            logger.debug(f"  [XSS] Crawl error: {e}")

        # Deduplicate
        return list(set(params))

    def _test_reflected_xss(self, url, param_name):
        """Test a specific parameter for reflected XSS."""
        findings = []
        parsed = urlparse(url)
        base_params = parse_qs(parsed.query, keep_blank_values=True)

        for payload in XSS_PAYLOADS:
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
                resp = self.session.get(test_url, timeout=DEFAULT_TIMEOUT, allow_redirects=True)

                # Check if payload is reflected unencoded
                if payload in resp.text:
                    # Verify it's actually in a dangerous context
                    context = self._analyze_context(resp.text, payload)
                    if context:
                        findings.append(Finding(
                            title=f"Reflected XSS in parameter '{param_name}'",
                            severity=SEVERITY_HIGH,
                            url=test_url,
                            description=(
                                f"The parameter '{param_name}' reflects user input without "
                                f"proper encoding. Payload found in {context} context."
                            ),
                            evidence=f"Payload: {payload}\nReflected in: {context}",
                            remediation=(
                                "Encode all user input before reflecting it in HTML. "
                                "Use context-aware output encoding (HTML entity, JS, URL encoding)."
                            ),
                            module=self.name,
                            cwe="CWE-79",
                        ))
                        break  # One confirmed XSS per param is enough

            except requests.RequestException:
                continue

        return findings

    def _analyze_context(self, html, payload):
        """Determine the reflection context of the payload."""
        idx = html.find(payload)
        if idx == -1:
            return None

        # Get surrounding context
        before = html[max(0, idx - 100):idx]
        after = html[idx:idx + len(payload) + 100]

        # Check if inside <script> tags
        if re.search(r"<script[^>]*>", before, re.IGNORECASE) and not re.search(
            r"</script>", before[before.rfind("<script"):], re.IGNORECASE
        ):
            return "JavaScript"

        # Check if inside an HTML attribute
        attr_match = re.search(r'[\w-]+\s*=\s*["\']?[^"\']*$', before)
        if attr_match:
            return "HTML attribute"

        # Check if inside HTML tags
        tag_match = re.search(r"<\w+[^>]*$", before)
        if tag_match:
            return "HTML tag"

        # Default: in HTML body
        return "HTML body"

    def _check_dom_xss(self, target):
        """Check for common DOM-based XSS sinks in JavaScript."""
        findings = []
        try:
            resp = self.session.get(target, timeout=DEFAULT_TIMEOUT)
        except requests.RequestException:
            return findings

        # Dangerous DOM sinks
        sinks = [
            (r"\.innerHTML\s*=", "innerHTML assignment"),
            (r"\.outerHTML\s*=", "outerHTML assignment"),
            (r"document\.write\s*\(", "document.write()"),
            (r"document\.writeln\s*\(", "document.writeln()"),
            (r"eval\s*\(", "eval()"),
            (r"setTimeout\s*\(\s*['\"]", "setTimeout with string"),
            (r"setInterval\s*\(\s*['\"]", "setInterval with string"),
        ]

        # Dangerous sources
        sources = [
            r"location\.hash",
            r"location\.search",
            r"location\.href",
            r"document\.URL",
            r"document\.referrer",
            r"window\.name",
            r"document\.cookie",
        ]

        for pattern, sink_name in sinks:
            matches = re.findall(pattern, resp.text)
            if matches:
                # Check if any source feeds into a sink nearby
                for source_pat in sources:
                    # Look for source within 500 chars of sink
                    for m in re.finditer(pattern, resp.text):
                        start = max(0, m.start() - 500)
                        region = resp.text[start:m.end() + 500]
                        if re.search(source_pat, region):
                            findings.append(Finding(
                                title=f"Potential DOM XSS: {sink_name}",
                                severity=SEVERITY_INFO,
                                url=target,
                                description=(
                                    f"A DOM XSS sink ({sink_name}) was found near a user-controllable "
                                    f"source ({source_pat}). Manual verification is recommended."
                                ),
                                evidence=f"Sink: {sink_name}, Source pattern: {source_pat}",
                                remediation="Avoid using dangerous DOM sinks. Use textContent instead of innerHTML.",
                                module=self.name,
                                cwe="CWE-79",
                            ))
                            break

        return findings
