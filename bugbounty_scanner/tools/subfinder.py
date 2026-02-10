"""Wrapper per Subfinder - enumerazione sottodomini passiva."""

import logging

from bugbounty_scanner.tools.base import BaseTool
from bugbounty_scanner.scanner import Finding
from bugbounty_scanner.config import SEVERITY_INFO

logger = logging.getLogger("bugbounty_scanner")


class SubfinderTool(BaseTool):
    """
    Subfinder - tool veloce per enumerazione sottodomini passiva.
    Usa fonti come VirusTotal, Shodan, SecurityTrails, Censys, ecc.
    https://github.com/projectdiscovery/subfinder
    """

    name = "subfinder"
    binary = "subfinder"
    install_url = "https://github.com/projectdiscovery/subfinder"

    def run(self, target, scan_result):
        self.check_installed()
        findings = []

        logger.info(f"  [Subfinder] Enumerazione sottodomini per {target.domain}")

        output = self.run_command(
            ["-d", target.domain, "-silent", "-all"],
            timeout=120,
        )

        if not output:
            return findings

        subdomains = [line.strip() for line in output.splitlines() if line.strip()]
        scan_result.subdomains = sorted(set(subdomains))

        if subdomains:
            logger.info(f"  [Subfinder] Trovati {len(subdomains)} sottodomini")
            findings.append(Finding(
                title=f"Sottodomini scoperti: {len(subdomains)}",
                severity=SEVERITY_INFO,
                url=target.base_url,
                description=f"Subfinder ha trovato {len(subdomains)} sottodomini tramite fonti OSINT.",
                evidence="\n".join(subdomains[:30]) + ("\n..." if len(subdomains) > 30 else ""),
                module=self.name,
            ))

        return findings
