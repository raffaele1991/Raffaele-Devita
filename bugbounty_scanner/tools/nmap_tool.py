"""Wrapper per Nmap - scansione porte e servizi."""

import logging
import re
import socket

from bugbounty_scanner.tools.base import BaseTool
from bugbounty_scanner.scanner import Finding
from bugbounty_scanner.config import SEVERITY_INFO, SEVERITY_LOW, SEVERITY_MEDIUM

logger = logging.getLogger("bugbounty_scanner")

# CDN che rispondono su tutte le porte, producendo falsi positivi
CDN_SIGNATURES = [
    "cloudfront", "cloudflare", "akamai", "fastly", "incapsula",
    "sucuri", "imperva", "cdn77", "stackpath", "edgecast",
    "azurefd", "awselb",
]

# Porte riservate ai servizi rischiosi da verificare
RISKY_SERVICES = {
    21: ("FTP", SEVERITY_MEDIUM, "FTP espone dati in chiaro. Usa SFTP."),
    23: ("Telnet", SEVERITY_MEDIUM, "Telnet è non cifrato. Usa SSH."),
    445: ("SMB", SEVERITY_MEDIUM, "SMB esposto a internet è rischioso."),
    3306: ("MySQL", SEVERITY_MEDIUM, "Database MySQL esposto a internet."),
    5432: ("PostgreSQL", SEVERITY_MEDIUM, "Database PostgreSQL esposto a internet."),
    6379: ("Redis", SEVERITY_MEDIUM, "Redis esposto a internet senza autenticazione."),
    27017: ("MongoDB", SEVERITY_MEDIUM, "MongoDB esposto a internet."),
    9200: ("Elasticsearch", SEVERITY_MEDIUM, "Elasticsearch esposto a internet."),
}


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

        # Detecta se il target è dietro un CDN
        is_cdn = self._detect_cdn(target, scan_result)
        if is_cdn:
            logger.info("  [Nmap] Target dietro CDN - i risultati delle porte potrebbero essere inaffidabili")

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
        service_map = {}

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
                    service_map[port] = (service, version)

        # Se troppe porte aperte (>100), probabilmente è un CDN catch-all
        if len(open_ports) > 100:
            logger.info(f"  [Nmap] {len(open_ports)} porte aperte - probabile CDN/firewall catch-all, scarto risultati porte rischiose")
            scan_result.open_ports = [80, 443] if 80 in open_ports and 443 in open_ports else []
            return findings

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

        # Cerca servizi potenzialmente pericolosi, ma verifica che siano reali
        for port in open_ports:
            if port in RISKY_SERVICES:
                svc_name, severity, desc = RISKY_SERVICES[port]

                # Se dietro CDN, non segnalare porte rischiose (falsi positivi)
                if is_cdn:
                    logger.info(f"  [Nmap] Porta {port} ({svc_name}) ignorata - target dietro CDN")
                    continue

                # Verifica che il servizio risponda davvero con il banner atteso
                if not self._verify_service(target.domain, port, svc_name, service_map):
                    logger.info(f"  [Nmap] Porta {port} ({svc_name}) non confermata, scartata")
                    continue

                findings.append(Finding(
                    title=f"Servizio rischioso esposto: {svc_name} (porta {port})",
                    severity=severity,
                    url=f"{target.domain}:{port}",
                    description=desc,
                    remediation=f"Limita l'accesso alla porta {port} con firewall. Non esporre {svc_name} a internet.",
                    module=self.name,
                ))

        return findings

    @staticmethod
    def _detect_cdn(target, scan_result):
        """Rileva se il target è dietro un CDN/WAF guardando tecnologie e header."""
        # Controlla le tecnologie già rilevate da httpx
        for tech in scan_result.technologies:
            tech_lower = tech.lower()
            if any(cdn in tech_lower for cdn in CDN_SIGNATURES):
                return True
        return False

    @staticmethod
    def _verify_service(domain, port, svc_name, service_map):
        """Verifica che un servizio rischioso sia realmente in ascolto."""
        # Se nmap ha identificato un servizio specifico con versione, è affidabile
        if port in service_map:
            service, version = service_map[port]
            expected = {
                "FTP": ["ftp"],
                "Telnet": ["telnet"],
                "SMB": ["smb", "microsoft-ds", "netbios"],
                "MySQL": ["mysql"],
                "PostgreSQL": ["postgresql", "postgres"],
                "Redis": ["redis"],
                "MongoDB": ["mongodb", "mongod"],
                "Elasticsearch": ["elasticsearch", "http"],
            }
            expected_names = expected.get(svc_name, [])
            service_lower = service.lower()

            # Se nmap vede "http" o "tcpwrapped" su porta DB, non è il servizio reale
            if service_lower in ("http", "https", "tcpwrapped", "http-proxy"):
                if svc_name not in ("Elasticsearch",):
                    return False

            # Se il servizio matchato è quello atteso, è confermato
            if any(exp in service_lower for exp in expected_names):
                return True

            # Se ha una versione specifica, è probabilmente reale
            if version and service_lower not in ("http", "https", "tcpwrapped"):
                return True

        # Fallback: prova connessione TCP e leggi il banner
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5)
            sock.connect((domain, port))
            banner = sock.recv(1024).decode("utf-8", errors="ignore")
            sock.close()

            # Verifica banner per servizi noti
            banner_signatures = {
                "FTP": ["220", "ftp"],
                "Telnet": ["\xff\xfd", "\xff\xfb"],
                "MySQL": ["mysql", "mariadb"],
                "PostgreSQL": ["postgresql", "pg_hba"],
                "Redis": ["redis", "+PONG"],
                "MongoDB": ["mongodb", "ismaster"],
                "Elasticsearch": ["elasticsearch", "cluster_name"],
            }
            sigs = banner_signatures.get(svc_name, [])
            banner_lower = banner.lower()
            return any(sig.lower() in banner_lower for sig in sigs)
        except Exception:
            return False
