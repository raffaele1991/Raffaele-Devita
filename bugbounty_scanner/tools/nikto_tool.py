"""Wrapper per Nikto - web server scanner."""

import logging
import os
import re
import tempfile
from urllib.parse import urlparse

from bugbounty_scanner.tools.base import BaseTool
from bugbounty_scanner.scanner import Finding
from bugbounty_scanner.config import (
    SEVERITY_HIGH, SEVERITY_MEDIUM, SEVERITY_LOW, SEVERITY_INFO,
)

logger = logging.getLogger("bugbounty_scanner")


class NiktoTool(BaseTool):
    """
    Nikto - scanner completo per web server, CGI, file pericolosi, versioni obsolete.
    https://cirt.net/Nikto2
    """

    name = "nikto"
    binary = "nikto"
    install_url = "https://github.com/sullo/nikto"

    def _run_nikto(self, target_url, output_file, use_ssl=None):
        """Esegue Nikto con le opzioni appropriate. Ritorna (stdout, file_content)."""
        parsed = urlparse(target_url)
        is_https = parsed.scheme == "https"

        args = [
            "-h", target_url,
            "-Format", "csv",
            "-output", output_file,
            "-nointeractive",
            "-nolookup",
            "-maxtime", "300s",
            "-Tuning", "1234567890abc",  # tutti i test
        ]

        # Gestione SSL esplicita
        if use_ssl is True or (use_ssl is None and is_https):
            args.append("-ssl")
        elif use_ssl is False:
            args.append("-nossl")

        output = self.run_command(args, timeout=360) or ""

        # Leggi anche il file CSV di output
        file_content = ""
        try:
            with open(output_file, "r") as f:
                file_content = f.read()
        except Exception:
            pass

        return output, file_content

    def run(self, target, scan_result):
        self.check_installed()
        findings = []

        logger.info(f"  [Nikto] Scansione web server su {target.base_url}")

        # Nikto richiede -output quando si usa -Format
        fd, output_file = tempfile.mkstemp(suffix=".csv")
        os.close(fd)

        output, file_content = self._run_nikto(target.base_url, output_file)

        # Se SSL fallisce, riprova senza SSL (scansione HTTP su porta HTTPS)
        ssl_failed = (
            "SSL negotiation failed" in output
            or "ssl negotiation failed" in output.lower()
            or ("error limit" in output.lower() and "ssl" in output.lower())
        )
        if ssl_failed:
            logger.warning("  [Nikto] SSL fallito, riprovo senza SSL...")
            # Ricrea il file di output
            try:
                os.unlink(output_file)
            except Exception:
                pass
            fd2, output_file = tempfile.mkstemp(suffix=".csv")
            os.close(fd2)
            output, file_content = self._run_nikto(target.base_url, output_file, use_ssl=False)

        # Cleanup file di output
        try:
            os.unlink(output_file)
        except Exception:
            pass

        if not output and not file_content:
            return findings

        # Parsa stdout (linee con + prefisso)
        all_lines = (output or "").splitlines()
        for line in all_lines:
            # Nikto CSV format: "host","IP","port","ref","method","URI","message"
            # Ma anche output in plain text con + prefisso
            if line.startswith("+"):
                message = line.lstrip("+ ").strip()

                if not message or "Target" in message or "Start" in message or "End" in message:
                    continue

                if any(x in message for x in ["host(s) tested", "item(s) reported"]):
                    continue

                # Filtra messaggi informativi di Nikto (non sono vulnerabilità)
                if any(x in message.lower() for x in [
                    "no cgi directories",
                    "allowed http methods",
                    "retrieved x-powered-by",
                    "uncommon header",
                    "options:",
                ]):
                    continue

                # Filtra errori interni di Nikto (non sono vulnerabilità)
                if message.upper().startswith("ERROR") or "ERROR:" in message:
                    logger.warning(f"  [Nikto] Errore interno ignorato: {message}")
                    continue

                # Filtra messaggi SSL/TLS non rilevanti
                if any(x in message.lower() for x in [
                    "ssl negotiation", "ssl info", "ssl certificate",
                    "cipher is", "issuer:", "hostname", "error limit",
                ]):
                    continue

                # Classifica la gravità
                severity = SEVERITY_LOW
                msg_lower = message.lower()
                if any(kw in msg_lower for kw in [
                    "remote code", "injection", "backdoor",
                    "command execution", "arbitrary file",
                ]) or re.search(r'\brce\b', msg_lower):
                    severity = SEVERITY_HIGH
                elif any(kw in msg_lower for kw in [
                    "xss", "cross-site", "sql", "directory listing",
                    "traversal", "lfi", "rfi", "default credential",
                    "default password",
                ]):
                    severity = SEVERITY_MEDIUM
                elif any(kw in message.lower() for kw in [
                    "outdated", "obsolete", "version", "header",
                    "information disclosure",
                ]):
                    severity = SEVERITY_LOW

                # Estrai riferimento OSVDB se presente
                osvdb = ""
                osvdb_match = re.search(r"OSVDB-(\d+)", message)
                if osvdb_match:
                    osvdb = f"OSVDB-{osvdb_match.group(1)}"

                findings.append(Finding(
                    title=f"[Nikto] {message[:80]}",
                    severity=severity,
                    url=target.base_url,
                    description=message,
                    evidence=osvdb if osvdb else "",
                    module=self.name,
                ))

        logger.info(f"  [Nikto] Trovati {len(findings)} problemi")
        return findings
