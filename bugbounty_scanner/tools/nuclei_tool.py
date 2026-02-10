"""Wrapper per Nuclei - vulnerability scanner basato su template."""

import logging
import os

from bugbounty_scanner.tools.base import BaseTool
from bugbounty_scanner.scanner import Finding
from bugbounty_scanner.config import (
    SEVERITY_CRITICAL, SEVERITY_HIGH, SEVERITY_MEDIUM, SEVERITY_LOW, SEVERITY_INFO,
)

logger = logging.getLogger("bugbounty_scanner")

SEVERITY_MAP = {
    "critical": SEVERITY_CRITICAL,
    "high": SEVERITY_HIGH,
    "medium": SEVERITY_MEDIUM,
    "low": SEVERITY_LOW,
    "info": SEVERITY_INFO,
}


class NucleiTool(BaseTool):
    """
    Nuclei - scanner di vulnerabilità basato su migliaia di template YAML.
    CVE, misconfigurations, exposed panels, default credentials, ecc.
    https://github.com/projectdiscovery/nuclei
    """

    name = "nuclei"
    binary = "nuclei"
    install_url = "https://github.com/projectdiscovery/nuclei"

    def __init__(self, severity_filter=None, tags=None, templates=None, rate_limit=100):
        super().__init__()
        self.severity_filter = severity_filter  # es: "critical,high,medium"
        self.tags = tags  # es: "cve,misconfig"
        self.templates = templates  # path a template custom
        self.rate_limit = rate_limit

    def run(self, target, scan_result):
        self.check_installed()
        findings = []

        # Costruisci la lista di URL da scansionare
        urls = [target.base_url]
        if hasattr(scan_result, "live_hosts") and scan_result.live_hosts:
            for host_line in scan_result.live_hosts:
                url = host_line.split(" ")[0]
                if url and url not in urls:
                    urls.append(url)

        urls_file = self.make_temp_file("\n".join(urls))

        logger.info(f"  [Nuclei] Scansione di {len(urls)} URL con template...")

        args = [
            "-l", urls_file,
            "-json",
            "-silent",
            "-rate-limit", str(self.rate_limit),
            "-bulk-size", "25",
            "-concurrency", "10",
        ]

        if self.severity_filter:
            args.extend(["-severity", self.severity_filter])

        if self.tags:
            args.extend(["-tags", self.tags])

        if self.templates:
            args.extend(["-t", self.templates])

        output = self.run_command(args, timeout=600, parse_json=True)

        if not output:
            logger.info("  [Nuclei] Nessun risultato")
            return findings

        if isinstance(output, dict):
            output = [output]

        for entry in output:
            if not isinstance(entry, dict):
                continue

            template_id = entry.get("template-id", entry.get("templateID", "unknown"))
            info = entry.get("info", {})
            name = info.get("name", template_id)
            severity = info.get("severity", "info").lower()
            description = info.get("description", "")
            reference = info.get("reference", [])
            tags = info.get("tags", [])
            matched_url = entry.get("matched-at", entry.get("matched", entry.get("host", "")))
            extracted = entry.get("extracted-results", [])
            matcher_name = entry.get("matcher-name", "")
            curl_command = entry.get("curl-command", "")

            evidence_parts = []
            if template_id:
                evidence_parts.append(f"Template: {template_id}")
            if matcher_name:
                evidence_parts.append(f"Matcher: {matcher_name}")
            if extracted:
                evidence_parts.append(f"Estratto: {', '.join(str(e) for e in extracted[:5])}")
            if curl_command:
                evidence_parts.append(f"Curl: {curl_command}")
            if tags:
                tag_str = ", ".join(tags) if isinstance(tags, list) else str(tags)
                evidence_parts.append(f"Tags: {tag_str}")

            remediation = ""
            if reference:
                if isinstance(reference, list):
                    remediation = "Riferimenti: " + ", ".join(reference[:3])
                else:
                    remediation = f"Riferimento: {reference}"

            findings.append(Finding(
                title=f"[Nuclei] {name}",
                severity=SEVERITY_MAP.get(severity, SEVERITY_INFO),
                url=matched_url,
                description=description or f"Nuclei template '{template_id}' ha trovato un match.",
                evidence="\n".join(evidence_parts),
                remediation=remediation,
                module=self.name,
            ))

        logger.info(f"  [Nuclei] Trovate {len(findings)} vulnerabilità")
        return findings
