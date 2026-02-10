"""Wrapper per Dalfox - XSS scanner avanzato con bypass WAF."""

import logging
import os
import json
import tempfile
import re

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

    def _parse_output(self, raw_content):
        """Parsa output Dalfox (JSON, JSONL, o testo [POC]...)."""
        entries = []
        if not raw_content:
            return entries

        # Prova JSON array
        try:
            parsed = json.loads(raw_content)
            if isinstance(parsed, list):
                return [e for e in parsed if isinstance(e, dict)]
            if isinstance(parsed, dict):
                return [parsed]
        except json.JSONDecodeError:
            pass

        # Prova JSONL (una riga JSON per linea) + testo plain
        for line in raw_content.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                if isinstance(obj, dict):
                    entries.append(obj)
                continue
            except json.JSONDecodeError:
                pass

            # Testo plain: "[POC][V][GET] https://..." o "[POC][R][GET] https://..."
            poc_match = re.search(r'https?://\S+', line)
            if poc_match and ("[POC]" in line or "[V]" in line):
                entry = {"data": poc_match.group(0), "_raw_line": line}
                # Estrai parametro dal URL se presente (es: ?param=payload)
                poc_url = poc_match.group(0)
                from urllib.parse import urlparse, parse_qs
                parsed_url = urlparse(poc_url)
                if parsed_url.query:
                    params = parse_qs(parsed_url.query)
                    for p, vals in params.items():
                        for v in vals:
                            if any(tag in v.lower() for tag in
                                   ["<script", "alert(", "onerror", "onload",
                                    "onfocus", "onmouse", "javascript:", "<img",
                                    "<svg", "prompt(", "confirm("]):
                                entry["param"] = p
                                entry["payload"] = v
                                break
                entries.append(entry)

        return entries

    def run(self, target, scan_result):
        self.check_installed()
        findings = []

        logger.info(f"  [Dalfox] Scansione XSS su {target.base_url}")

        # Usa file di output come backup
        fd, output_file = tempfile.mkstemp(suffix=".json")
        os.close(fd)

        args = [
            "url", target.base_url,
            "--format", "json",
            "--timeout", "10",
            "--worker", "10",
            "--mining-dict-word",
            "--deep-domxss",
            "--follow-redirects",
            "-o", output_file,
        ]

        # Aggiungi header custom
        args.extend(self.get_header_args("-H"))

        # Cattura stdout (contiene --format json output)
        stdout_output = self.run_command(args, timeout=300) or ""

        # Leggi anche il file di output
        file_content = ""
        try:
            with open(output_file, "r") as f:
                file_content = f.read().strip()
        except Exception:
            pass
        finally:
            try:
                os.unlink(output_file)
            except Exception:
                pass

        # Log per debug
        if stdout_output:
            logger.debug(f"  [Dalfox] stdout ({len(stdout_output)} chars): {stdout_output[:500]}")
        if file_content:
            logger.debug(f"  [Dalfox] file output ({len(file_content)} chars): {file_content[:500]}")

        # Parsa entrambi gli output e unisci
        entries_stdout = self._parse_output(stdout_output)
        entries_file = self._parse_output(file_content)

        # Usa stdout come primario (ha --format json), file come fallback
        entries = entries_stdout if entries_stdout else entries_file

        if not entries:
            logger.info("  [Dalfox] Nessun XSS trovato")
            return findings

        logger.info(f"  [Dalfox] Parsing {len(entries)} entry...")

        seen_urls = set()  # Evita duplicati
        for entry in entries:
            if not isinstance(entry, dict):
                continue

            # Dalfox JSON fields (copre v2.x e v3.x)
            poc_url = (entry.get("data") or entry.get("proof_of_concept")
                       or entry.get("poc") or "")
            param = entry.get("param", "")
            payload = entry.get("payload", "")
            message = entry.get("message_str", entry.get("message", ""))
            inject_type = entry.get("inject_type", "")
            method = entry.get("method", "GET")
            vuln_type = entry.get("type", "")
            cwe = entry.get("cwe", "CWE-79")
            raw_line = entry.get("_raw_line", "")
            severity_str = entry.get("severity", "")

            # Dedup: se stessa URL PoC, salta
            dedup_key = poc_url or f"{target.base_url}:{param}:{payload}"
            if dedup_key in seen_urls:
                continue
            seen_urls.add(dedup_key)

            # Se non c'è PoC URL e non c'è payload, è un falso positivo
            if not poc_url and not payload and not raw_line:
                logger.debug(f"  [Dalfox] Entry senza PoC/payload scartata: {entry}")
                continue

            severity = SEVERITY_HIGH
            if "dom" in vuln_type.lower() or "dom" in inject_type.lower():
                severity = SEVERITY_MEDIUM

            # Costruisci evidenza dettagliata per il triage
            evidence_parts = []
            if poc_url:
                evidence_parts.append(f"PoC URL: {poc_url}")
            if method:
                evidence_parts.append(f"Metodo: {method}")
            if param:
                evidence_parts.append(f"Parametro vulnerabile: {param}")
            if payload:
                evidence_parts.append(f"Payload XSS: {payload}")
            if inject_type:
                evidence_parts.append(f"Tipo iniezione: {inject_type}")
            if raw_line:
                evidence_parts.append(f"Output Dalfox: {raw_line}")

            # Costruisci curl command per riprodurre
            if poc_url:
                curl_cmd = f"curl -s '{poc_url}'"
                if self._custom_headers:
                    for k, v in self._custom_headers.items():
                        curl_cmd += f" -H '{k}: {v}'"
                evidence_parts.append(f"\nComando per riprodurre:\n{curl_cmd}")

            # Descrizione dettagliata per Intigriti/HackerOne
            desc_parts = []
            desc_parts.append("Dalfox ha trovato una vulnerabilità XSS (Cross-Site Scripting)")
            if param:
                desc_parts.append(f"nel parametro `{param}`")
            desc_parts.append(f"su {target.base_url}.")
            if inject_type:
                desc_parts.append(f"Tipo di iniezione: {inject_type}.")
            if payload:
                desc_parts.append(f"Il payload `{payload}` viene eseguito nel browser senza sanitizzazione.")
            if message:
                desc_parts.append(message)

            findings.append(Finding(
                title=f"XSS ({inject_type or 'Reflected'})" + (f" in parametro '{param}'" if param else f" su {target.domain}"),
                severity=severity,
                url=poc_url or target.base_url,
                description=" ".join(desc_parts),
                evidence="\n".join(evidence_parts),
                remediation=(
                    "1. Applica output encoding contestuale (HTML entities, JS escaping, URL encoding). "
                    "2. Implementa Content-Security-Policy con 'script-src' restrittivo. "
                    "3. Usa framework con auto-escaping (React, Angular, Vue). "
                    "4. Valida e sanitizza l'input lato server."
                ),
                module=self.name,
                cwe=cwe or "CWE-79",
            ))

        logger.info(f"  [Dalfox] Trovati {len(findings)} XSS")
        return findings
