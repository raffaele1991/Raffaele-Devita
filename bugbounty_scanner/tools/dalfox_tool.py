"""Wrapper per Dalfox - XSS scanner avanzato con bypass WAF."""

import logging

from bugbounty_scanner.tools.base import BaseTool
from bugbounty_scanner.scanner import Finding
from bugbounty_scanner.config import SEVERITY_HIGH, SEVERITY_MEDIUM

logger = logging.getLogger("bugbounty_scanner")


class DalfoxTool(BaseTool):
    """
    Dalfox - scanner XSS avanzato con analisi DOM, bypass WAF, e mining di parametri.
    https://github.com/hahwul/dalfox
    """

    name = "dalfox"
    binary = "dalfox"
    install_url = "https://github.com/hahwul/dalfox"

    def run(self, target, scan_result):
        self.check_installed()
        findings = []

        logger.info(f"  [Dalfox] Scansione XSS su {target.base_url}")

        args = [
            "url", target.base_url,
            "--silence",
            "--format", "json",
            "--timeout", "10",
            "--worker", "10",
            "--mining-dict-word",   # mining automatico di parametri
            "--deep-domxss",        # analisi DOM XSS approfondita
            "--follow-redirects",
        ]

        output = self.run_command(args, timeout=300, parse_json=True)

        if not output:
            logger.info("  [Dalfox] Nessun XSS trovato")
            return findings

        if isinstance(output, dict):
            output = [output]

        for entry in output:
            if not isinstance(entry, dict):
                continue

            vuln_type = entry.get("type", "")
            poc_url = entry.get("proof_of_concept", entry.get("poc", entry.get("data", "")))
            param = entry.get("param", "")
            payload = entry.get("payload", "")
            message = entry.get("message", entry.get("message_str", ""))
            inject_type = entry.get("inject_type", "")

            severity = SEVERITY_HIGH
            if "dom" in vuln_type.lower() or "dom" in inject_type.lower():
                severity = SEVERITY_MEDIUM

            evidence_parts = []
            if payload:
                evidence_parts.append(f"Payload: {payload}")
            if param:
                evidence_parts.append(f"Parametro: {param}")
            if inject_type:
                evidence_parts.append(f"Tipo: {inject_type}")
            if poc_url:
                evidence_parts.append(f"PoC: {poc_url}")

            findings.append(Finding(
                title=f"XSS trovato da Dalfox" + (f" in '{param}'" if param else ""),
                severity=severity,
                url=poc_url or target.base_url,
                description=(
                    f"Dalfox ha trovato una vulnerabilità XSS{' nel parametro ' + param if param else ''}. "
                    f"{message}"
                ),
                evidence="\n".join(evidence_parts),
                remediation=(
                    "Applica output encoding contestuale (HTML, JS, URL). "
                    "Implementa Content-Security-Policy. "
                    "Usa framework con auto-escaping (React, Angular, ecc.)."
                ),
                module=self.name,
                cwe="CWE-79",
            ))

        logger.info(f"  [Dalfox] Trovati {len(findings)} XSS")
        return findings
