"""Wrapper per Nmap - scansione porte e servizi."""

import logging
import re

from bugbounty_scanner.tools.base import BaseTool
from bugbounty_scanner.scanner import Finding
from bugbounty_scanner.config import SEVERITY_INFO, SEVERITY_LOW, SEVERITY_MEDIUM

logger = logging.getLogger("bugbounty_scanner")


class NmapTool(BaseTool):
    """
    Nmap - lo scanner di rete più usato al mondo.
    https://nmap.org/
    """

    name = "nmap"
    binary = "nmap"
    install_url = "https://nmap.org/download.html"

    def __init__(self, scan_type="default"):
        super().__init__()
        self.scan_type = scan_type  # default, quick, full

    def run(self, target, scan_result):
        self.check_installed()
        findings = []

        logger.info(f"  [Nmap] Scansione porte su {target.domain}")

        if self.scan_type == "quick":
            args = ["-sV", "--top-ports", "100", "-T4", target.domain]
        elif self.scan_type == "full":
            args = ["-sV", "-sC", "-p-", "-T4", target.domain]
        else:
            args = ["-sV", "--top-ports", "1000", "-T4", target.domain]

        output = self.run_command(args, timeout=600)

        if not output:
            return findings

        # Parsa l'output di nmap
        open_ports = []
        services = []

        for line in output.splitlines():
            # Cerca linee tipo: 80/tcp   open  http    Apache httpd 2.4.41
            match = re.match(
                r"(\d+)/(\w+)\s+(open|filtered)\s+(\S+)\s*(.*)", line
            )
            if match:
                port = int(match.group(1))
                protocol = match.group(2)
                state = match.group(3)
                service = match.group(4)
                version = match.group(5).strip()

                if state == "open":
                    open_ports.append(port)
                    services.append(f"{port}/{protocol} - {service} {version}".strip())

        scan_result.open_ports = sorted(open_ports)

        if services:
            findings.append(Finding(
                title=f"Porte aperte: {len(open_ports)} (Nmap)",
                severity=SEVERITY_INFO,
                url=target.base_url,
                description=f"Nmap ha trovato {len(open_ports)} porte aperte con versioni dei servizi.",
                evidence="\n".join(services),
                module=self.name,
            ))

        # Cerca servizi potenzialmente pericolosi
        risky_services = {
            21: ("FTP", SEVERITY_MEDIUM, "FTP espone dati in chiaro. Usa SFTP."),
            23: ("Telnet", SEVERITY_MEDIUM, "Telnet è non cifrato. Usa SSH."),
            445: ("SMB", SEVERITY_MEDIUM, "SMB esposto a internet è rischioso."),
            3306: ("MySQL", SEVERITY_MEDIUM, "Database MySQL esposto a internet."),
            5432: ("PostgreSQL", SEVERITY_MEDIUM, "Database PostgreSQL esposto a internet."),
            6379: ("Redis", SEVERITY_MEDIUM, "Redis esposto a internet senza autenticazione."),
            27017: ("MongoDB", SEVERITY_MEDIUM, "MongoDB esposto a internet."),
            9200: ("Elasticsearch", SEVERITY_MEDIUM, "Elasticsearch esposto a internet."),
        }

        for port in open_ports:
            if port in risky_services:
                svc_name, severity, desc = risky_services[port]
                findings.append(Finding(
                    title=f"Servizio rischioso esposto: {svc_name} (porta {port})",
                    severity=severity,
                    url=f"{target.domain}:{port}",
                    description=desc,
                    remediation=f"Limita l'accesso alla porta {port} con firewall. Non esporre {svc_name} a internet.",
                    module=self.name,
                ))

        return findings
