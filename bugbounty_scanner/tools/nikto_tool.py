"""Wrapper per Nikto - web server scanner."""

import logging
import os
import re
import tempfile

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

    def run(self, target, scan_result):
        self.check_installed()
        findings = []

        logger.info(f"  [Nikto] Scansione web server su {target.base_url}")

        # Nikto richiede -output quando si usa -Format
        fd, output_file = tempfile.mkstemp(suffix=".csv")
        os.close(fd)

        args = [
            "-h", target.base_url,
            "-Format", "csv",
            "-output", output_file,
            "-nointeractive",
            "-maxtime", "300s",
            "-Tuning", "1234567890abc",  # tutti i test
        ]

        output = self.run_command(args, timeout=360)

        # Leggi anche il file CSV di output
        file_content = ""
        try:
            with open(output_file, "r") as f:
                file_content = f.read()
        except Exception:
            pass
        finally:
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

                # Filtra errori interni di Nikto (non sono vulnerabilità)
                if message.upper().startswith("ERROR") or "ERROR:" in message:
                    logger.warning(f"  [Nikto] Errore interno ignorato: {message}")
                    continue

                # Classifica la gravità
                severity = SEVERITY_LOW
                if any(kw in message.lower() for kw in [
                    "remote code", "rce", "injection", "backdoor",
                    "command execution", "arbitrary file",
                ]):
                    severity = SEVERITY_HIGH
                elif any(kw in message.lower() for kw in [
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
