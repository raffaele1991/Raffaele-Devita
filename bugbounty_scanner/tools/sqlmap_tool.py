"""Wrapper per SQLMap - testing automatico SQL Injection."""

import logging
import os
import re

from bugbounty_scanner.tools.base import BaseTool
from bugbounty_scanner.scanner import Finding
from bugbounty_scanner.config import SEVERITY_CRITICAL, SEVERITY_HIGH

logger = logging.getLogger("bugbounty_scanner")


class SqlmapTool(BaseTool):
    """
    SQLMap - tool automatico per SQL injection e database takeover.
    https://sqlmap.org/
    """

    name = "sqlmap"
    binary = "sqlmap"
    install_url = "https://sqlmap.org/"

    def __init__(self, level=1, risk=1):
        super().__init__()
        self.level = level  # 1-5: livello di test (più alto = più payload)
        self.risk = risk    # 1-3: rischio (più alto = payload più pericolosi)

    def run(self, target, scan_result):
        self.check_installed()
        findings = []

        # SQLMap funziona meglio con URL con parametri
        if "?" not in target.base_url:
            logger.info("  [SQLMap] Nessun parametro URL da testare, salto")
            return findings

        logger.info(f"  [SQLMap] Testing SQL injection su {target.base_url}")

        args = [
            "-u", target.base_url,
            "--batch",          # non chiedere input all'utente
            "--level", str(self.level),
            "--risk", str(self.risk),
            "--threads", "4",
            "--timeout", "15",
            "--retries", "1",
            "--output-dir", "/tmp/sqlmap_output",
            "--flush-session",
            "--smart",          # esegui test solo se euristiche positive
        ]

        output = self.run_command(args, timeout=300)

        if not output:
            return findings

        # Parsa l'output di sqlmap
        vulnerable_params = []
        injection_types = []
        dbms = ""

        for line in output.splitlines():
            line_lower = line.lower().strip()

            # Cerca parametri vulnerabili
            if "parameter '" in line_lower and "is vulnerable" in line_lower:
                match = re.search(r"parameter '(\w+)'", line, re.IGNORECASE)
                if match:
                    vulnerable_params.append(match.group(1))

            # Tipo di injection
            if "type:" in line_lower and ("boolean" in line_lower or "time" in line_lower
                                          or "union" in line_lower or "error" in line_lower
                                          or "stacked" in line_lower):
                injection_types.append(line.strip())

            # DBMS identificato
            if "back-end dbms:" in line_lower:
                dbms = line.split(":", 1)[1].strip()

            # sqlmap conferma la vulnerabilità
            if "sqlmap identified the following injection point" in line_lower:
                vulnerable_params.append("confirmed")

        if vulnerable_params:
            evidence_parts = []
            if dbms:
                evidence_parts.append(f"DBMS: {dbms}")
            if injection_types:
                evidence_parts.append("Tipi di injection:\n" + "\n".join(injection_types[:5]))

            findings.append(Finding(
                title=f"SQL Injection confermata da SQLMap",
                severity=SEVERITY_CRITICAL,
                url=target.base_url,
                description=(
                    f"SQLMap ha confermato SQL injection nei parametri: "
                    f"{', '.join(set(p for p in vulnerable_params if p != 'confirmed'))}. "
                    f"{'DBMS: ' + dbms + '.' if dbms else ''}"
                ),
                evidence="\n".join(evidence_parts),
                remediation=(
                    "Usa query parametrizzate/prepared statement. "
                    "Non concatenare mai input utente nelle query SQL. "
                    "Implementa un WAF come mitigazione aggiuntiva."
                ),
                module=self.name,
                cwe="CWE-89",
            ))
            logger.info(f"  [SQLMap] VULNERABILITA' CONFERMATA!")
        else:
            logger.info(f"  [SQLMap] Nessuna SQL injection trovata")

        return findings
