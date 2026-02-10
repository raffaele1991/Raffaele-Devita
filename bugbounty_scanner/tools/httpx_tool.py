"""Wrapper per httpx - HTTP probing e fingerprinting."""

import logging
import json

from bugbounty_scanner.tools.base import BaseTool
from bugbounty_scanner.scanner import Finding
from bugbounty_scanner.config import SEVERITY_INFO, SEVERITY_LOW

logger = logging.getLogger("bugbounty_scanner")


class HttpxTool(BaseTool):
    """
    httpx - tool veloce per HTTP probing, tech detection, status codes.
    https://github.com/projectdiscovery/httpx
    """

    name = "httpx"
    binary = "httpx"
    install_url = "https://github.com/projectdiscovery/httpx"

    def run(self, target, scan_result):
        self.check_installed()
        findings = []

        # Se abbiamo sottodomini, facciamo probe su tutti
        hosts = scan_result.subdomains if scan_result.subdomains else [target.domain]

        logger.info(f"  [httpx] Probing {len(hosts)} host...")

        # Crea file con la lista degli host
        hosts_file = self.make_temp_file("\n".join(hosts))

        output = self.run_command(
            [
                "-l", hosts_file,
                "-silent",
                "-json",
                "-status-code",
                "-title",
                "-tech-detect",
                "-server",
                "-content-length",
                "-follow-redirects",
            ],
            timeout=180,
            parse_json=True,
        )

        if not output:
            return findings

        if isinstance(output, dict):
            output = [output]

        live_hosts = []
        technologies = set()

        for entry in output:
            if not isinstance(entry, dict):
                continue

            host = entry.get("url", entry.get("input", ""))
            status = entry.get("status_code", entry.get("status-code", 0))
            title = entry.get("title", "")
            tech = entry.get("tech", [])
            server = entry.get("webserver", entry.get("server", ""))

            if host:
                live_hosts.append(f"{host} [{status}] {title}")

            if tech:
                technologies.update(tech)

            if server:
                technologies.add(server)

        scan_result.technologies = sorted(technologies)
        scan_result.live_hosts = live_hosts

        if live_hosts:
            findings.append(Finding(
                title=f"Host attivi: {len(live_hosts)}",
                severity=SEVERITY_INFO,
                url=target.base_url,
                description=f"httpx ha trovato {len(live_hosts)} host attivi.",
                evidence="\n".join(live_hosts[:20]),
                module=self.name,
            ))

        if technologies:
            findings.append(Finding(
                title=f"Tecnologie rilevate: {len(technologies)}",
                severity=SEVERITY_INFO,
                url=target.base_url,
                description="Tecnologie rilevate tramite httpx.",
                evidence=", ".join(sorted(technologies)),
                module=self.name,
            ))

        return findings
