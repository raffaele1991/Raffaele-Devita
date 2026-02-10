"""Reconnaissance module: subdomain enumeration, port scanning, tech detection."""

import socket
import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from bugbounty_scanner.config import (
    COMMON_PORTS,
    DEFAULT_TIMEOUT,
    DEFAULT_USER_AGENT,
    SUBDOMAIN_WORDLIST,
    SEVERITY_INFO,
    SEVERITY_LOW,
    INFO_LEAK_HEADERS,
)
from bugbounty_scanner.scanner import Finding

logger = logging.getLogger("bugbounty_scanner")


class ReconModule:
    """Performs reconnaissance: subdomain enumeration, port scanning, tech fingerprinting."""

    name = "recon"

    def __init__(self, enum_subdomains=True, scan_ports=True, detect_tech=True, threads=10, http_session=None):
        self.enum_subdomains = enum_subdomains
        self.scan_ports = scan_ports
        self.detect_tech = detect_tech
        self.threads = threads
        if http_session:
            self.session = http_session
        else:
            from bugbounty_scanner.http_session import HttpSession
            self.session = HttpSession()

    def run(self, target, scan_result):
        """Run all recon tasks and return findings."""
        findings = []
        domain = urlparse(target).netloc

        if self.enum_subdomains:
            subs = self._enumerate_subdomains(domain)
            scan_result.subdomains = subs
            if subs:
                findings.append(Finding(
                    title="Subdomains Discovered",
                    severity=SEVERITY_INFO,
                    url=target,
                    description=f"Found {len(subs)} subdomains via DNS brute-force.",
                    evidence=", ".join(subs[:20]) + ("..." if len(subs) > 20 else ""),
                    module=self.name,
                ))

        if self.scan_ports:
            ports = self._scan_ports(domain)
            scan_result.open_ports = ports
            if ports:
                findings.append(Finding(
                    title="Open Ports Detected",
                    severity=SEVERITY_INFO,
                    url=target,
                    description=f"Found {len(ports)} open ports.",
                    evidence=", ".join(str(p) for p in ports),
                    module=self.name,
                ))

        if self.detect_tech:
            tech_findings = self._detect_technologies(target)
            techs = [f.evidence for f in tech_findings]
            scan_result.technologies = techs
            findings.extend(tech_findings)

        return findings

    def _enumerate_subdomains(self, domain):
        """Brute-force subdomain discovery via DNS resolution."""
        logger.info(f"  Enumerating subdomains for {domain}")
        found = []

        def check(sub):
            fqdn = f"{sub}.{domain}"
            try:
                socket.getaddrinfo(fqdn, None, socket.AF_INET, socket.SOCK_STREAM)
                return fqdn
            except socket.gaierror:
                return None

        with ThreadPoolExecutor(max_workers=self.threads) as pool:
            futures = {pool.submit(check, sub): sub for sub in SUBDOMAIN_WORDLIST}
            for fut in as_completed(futures):
                result = fut.result()
                if result:
                    found.append(result)
                    logger.debug(f"    Found subdomain: {result}")

        return sorted(found)

    def _scan_ports(self, host):
        """TCP connect scan on common ports."""
        logger.info(f"  Scanning ports on {host}")
        open_ports = []

        def check_port(port):
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.settimeout(2)
                    if s.connect_ex((host, port)) == 0:
                        return port
            except (socket.timeout, OSError):
                pass
            return None

        with ThreadPoolExecutor(max_workers=self.threads) as pool:
            futures = {pool.submit(check_port, p): p for p in COMMON_PORTS}
            for fut in as_completed(futures):
                result = fut.result()
                if result is not None:
                    open_ports.append(result)
                    logger.debug(f"    Port {result} open")

        return sorted(open_ports)

    def _detect_technologies(self, target):
        """Fingerprint technologies from HTTP headers, HTML content, cookies."""
        findings = []
        try:
            resp = self.session.get(target, timeout=DEFAULT_TIMEOUT, allow_redirects=True)
        except requests.RequestException as e:
            logger.warning(f"  Tech detection request failed: {e}")
            return findings

        # Check info-leaking headers
        for header in INFO_LEAK_HEADERS:
            value = resp.headers.get(header)
            if value:
                findings.append(Finding(
                    title=f"Technology Detected via Header: {header}",
                    severity=SEVERITY_INFO,
                    url=target,
                    description=f"The '{header}' response header reveals technology information.",
                    evidence=f"{header}: {value}",
                    remediation=f"Remove or obfuscate the '{header}' header in production.",
                    module=self.name,
                ))

        # HTML-based detection
        try:
            soup = BeautifulSoup(resp.text, "html.parser")

            # Generator meta tag
            gen = soup.find("meta", attrs={"name": "generator"})
            if gen and gen.get("content"):
                findings.append(Finding(
                    title="CMS/Framework Detected via Meta Tag",
                    severity=SEVERITY_INFO,
                    url=target,
                    description="A generator meta tag reveals the CMS or framework in use.",
                    evidence=f"generator: {gen['content']}",
                    module=self.name,
                ))

            # Common framework patterns in HTML
            patterns = {
                "WordPress": [r"wp-content", r"wp-includes"],
                "Drupal": [r"sites/default/files", r"Drupal\.settings"],
                "Joomla": [r"/media/jui/", r"Joomla!"],
                "React": [r"__NEXT_DATA__", r"_reactRootContainer"],
                "Angular": [r"ng-version", r"ng-app"],
                "Vue.js": [r"__vue__", r"v-cloak"],
                "Laravel": [r"laravel_session", r"csrf-token"],
                "Django": [r"csrfmiddlewaretoken", r"__admin"],
                "ASP.NET": [r"__VIEWSTATE", r"__EVENTVALIDATION"],
                "Spring": [r"JSESSIONID"],
            }

            body_text = resp.text
            for tech_name, tech_patterns in patterns.items():
                for pat in tech_patterns:
                    if re.search(pat, body_text, re.IGNORECASE):
                        findings.append(Finding(
                            title=f"Framework Detected: {tech_name}",
                            severity=SEVERITY_INFO,
                            url=target,
                            description=f"Detected {tech_name} based on response content patterns.",
                            evidence=f"Pattern matched: {pat}",
                            module=self.name,
                        ))
                        break  # one match per tech is enough

        except Exception as e:
            logger.debug(f"  HTML tech detection error: {e}")

        # Cookie-based detection
        for cookie in resp.cookies:
            cookie_name = cookie.name.lower()
            tech_cookies = {
                "phpsessid": "PHP",
                "jsessionid": "Java/Spring",
                "asp.net_sessionid": "ASP.NET",
                "laravel_session": "Laravel",
                "csrftoken": "Django",
                "_rails_session": "Ruby on Rails",
            }
            for ck, tech in tech_cookies.items():
                if ck in cookie_name:
                    findings.append(Finding(
                        title=f"Technology Detected via Cookie: {tech}",
                        severity=SEVERITY_INFO,
                        url=target,
                        description=f"Cookie name '{cookie.name}' reveals {tech}.",
                        evidence=f"Cookie: {cookie.name}",
                        module=self.name,
                    ))

        return findings
