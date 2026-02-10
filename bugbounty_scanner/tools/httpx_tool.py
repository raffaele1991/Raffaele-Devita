"""Wrapper per httpx - HTTP probing e fingerprinting (ProjectDiscovery Go version)."""

import logging
import json
import subprocess

from bugbounty_scanner.tools.base import BaseTool, ToolNotFoundError
from bugbounty_scanner.scanner import Finding
from bugbounty_scanner.config import SEVERITY_INFO, SEVERITY_LOW

logger = logging.getLogger("bugbounty_scanner")


class HttpxTool(BaseTool):
    """
    httpx - tool veloce per HTTP probing, tech detection, status codes.
    https://github.com/projectdiscovery/httpx

    NOTA: NON confondere con Python httpx (pip install httpx) che è una
    libreria HTTP diversa. Qui serve il binario Go di ProjectDiscovery.
    """

    name = "httpx"
    binary = "httpx"
    install_url = "https://github.com/projectdiscovery/httpx"

    def _is_go_httpx(self, binary_path: str) -> bool:
        """Verifica che il binario sia httpx Go (ProjectDiscovery), non Python httpx."""
        try:
            result = subprocess.run(
                [binary_path, "-version"],
                capture_output=True, text=True, timeout=10,
            )
            combined = (result.stdout + result.stderr).lower()
            # Go httpx mostra "projectdiscovery" o "httpx v1.x.x" nella version
            if "projectdiscovery" in combined or "current v" in combined:
                return True
            # Python httpx mostra "httpx" con "python" o "pip" related output
            if "python" in combined or "usage: httpx" in combined:
                return False
            # Se supporta -json è Go httpx
            test = subprocess.run(
                [binary_path, "-h"],
                capture_output=True, text=True, timeout=10,
            )
            help_text = test.stdout + test.stderr
            return "-json" in help_text and "-silent" in help_text
        except Exception:
            return False

    def _find_binary(self):
        """Override: cerca httpx Go e verifica che non sia Python httpx."""
        # 1) Cerca nelle directory Go/local (priorità)
        import os
        import shutil
        for extra_dir in self._EXTRA_PATHS:
            candidate = os.path.join(extra_dir, self.binary)
            if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                if self._is_go_httpx(candidate):
                    return candidate

        # 2) Cerca nel PATH di sistema, ma valida
        path = shutil.which(self.binary)
        if path and self._is_go_httpx(path):
            return path

        return None

    def check_installed(self):
        """Override: messaggio specifico se trova Python httpx."""
        self._binary_path = self._find_binary()
        if self._binary_path:
            return
        # Controlla se è Python httpx (messaggio di errore specifico)
        import shutil
        any_httpx = shutil.which(self.binary)
        if any_httpx:
            raise ToolNotFoundError(
                f"Trovato '{any_httpx}' ma è Python httpx (pip), non il tool Go.\n"
                f"Installa la versione Go: go install github.com/projectdiscovery/httpx/cmd/httpx@latest\n"
                f"Assicurati che ~/go/bin sia nel PATH: export PATH=$PATH:~/go/bin"
            )
        raise ToolNotFoundError(
            f"'{self.binary}' (Go - ProjectDiscovery) non trovato.\n"
            f"Installalo: go install github.com/projectdiscovery/httpx/cmd/httpx@latest\n"
            f"Info: {self.install_url}"
        )

    def run(self, target, scan_result):
        self.check_installed()
        findings = []

        # Se abbiamo sottodomini, facciamo probe su tutti
        hosts = scan_result.subdomains if scan_result.subdomains else [target.domain]

        logger.info(f"  [httpx] Probing {len(hosts)} host...")

        # Crea file con la lista degli host
        hosts_file = self.make_temp_file("\n".join(hosts))

        args = [
            "-l", hosts_file,
            "-silent",
            "-json",
            "-status-code",
            "-title",
            "-tech-detect",
            "-server",
            "-content-length",
            "-follow-redirects",
        ] + self.get_header_args("-H")

        output = self.run_command(args, timeout=180, parse_json=True)

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
