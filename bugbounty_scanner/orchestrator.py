"""Orchestratore Pro - coordina tutti i tool professionali in sequenza intelligente."""

import time
import logging
from dataclasses import dataclass
from urllib.parse import urlparse

from bugbounty_scanner.scanner import ScanResult, Finding
from bugbounty_scanner.tools.base import ToolNotFoundError

logger = logging.getLogger("bugbounty_scanner")


@dataclass
class Target:
    """Rappresenta il target della scansione."""

    raw: str
    base_url: str
    domain: str
    scheme: str

    @classmethod
    def from_url(cls, url):
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        url = url.rstrip("/")
        parsed = urlparse(url)
        return cls(
            raw=url,
            base_url=url,
            domain=parsed.netloc,
            scheme=parsed.scheme,
        )


# Pipeline di default: l'ordine conta!
# 1. Ricognizione → 2. Probing → 3. Scansione → 4. Exploit testing
DEFAULT_PIPELINE = [
    "subfinder",           # 1. Trova sottodomini
    "httpx",               # 2. Verifica quali sono attivi + tech detection
    "subdomain_takeover",  # 3. Cerca subdomain takeover (CNAME dangling)
    "nmap",                # 4. Scansione porte e servizi
    "ffuf",                # 5. Directory/file fuzzing
    "nuclei",              # 6. Vulnerability scanning con template (il pezzo forte)
    "nikto",               # 7. Web server scanning
    "dalfox",              # 8. XSS avanzato
    "sqlmap",              # 9. SQL injection avanzata
    # Moduli interni (dal vecchio scanner)
    "headers",             # 10. Security headers
    "sensitive_files",     # 11. File sensibili (backup del ffuf)
]


class Orchestrator:
    """
    Orchestratore che esegue i tool in ordine intelligente.

    La pipeline è progettata così:
    1. Prima la ricognizione (subfinder → httpx → nmap)
    2. Poi il fuzzing (ffuf)
    3. Poi la scansione vulnerabilità (nuclei → nikto → dalfox → sqlmap)
    4. Infine i check interni (headers, sensitive_files)

    Se un tool non è installato, viene saltato con un warning.
    I risultati di ogni fase alimentano le fasi successive.
    """

    def __init__(self, target_url, pipeline=None, skip_missing=True):
        self.target = Target.from_url(target_url)
        self.pipeline = pipeline or DEFAULT_PIPELINE
        self.skip_missing = skip_missing
        self.result = ScanResult(target=self.target.base_url)
        self._tools = {}

    def register(self, name, tool_instance):
        """Registra un tool nell'orchestratore."""
        self._tools[name] = tool_instance

    def run(self) -> ScanResult:
        """Esegue la pipeline completa."""
        self.result.start_time = time.time()

        total = len(self.pipeline)
        logger.info(f"Pipeline con {total} fasi su {self.target.base_url}")
        print(f"\n  Target: {self.target.base_url}")
        print(f"  Pipeline: {' → '.join(self.pipeline)}\n")

        for i, tool_name in enumerate(self.pipeline, 1):
            if tool_name not in self._tools:
                logger.warning(f"  [{i}/{total}] Tool '{tool_name}' non registrato, salto")
                continue

            tool = self._tools[tool_name]
            phase_label = f"[{i}/{total}] {tool_name.upper()}"

            print(f"  {'─'*50}")
            print(f"  {phase_label}")
            print(f"  {'─'*50}")

            try:
                start = time.time()
                findings = tool.run(self.target, self.result)
                elapsed = time.time() - start

                if findings:
                    self.result.findings.extend(findings)
                    # Conteggio per gravità
                    sev_counts = {}
                    for f in findings:
                        sev_counts[f.severity] = sev_counts.get(f.severity, 0) + 1
                    sev_str = ", ".join(f"{k}: {v}" for k, v in sorted(sev_counts.items()))
                    print(f"  Risultato: {len(findings)} trovati ({sev_str}) [{elapsed:.1f}s]")
                else:
                    print(f"  Risultato: pulito [{elapsed:.1f}s]")

            except ToolNotFoundError as e:
                msg = f"Tool '{tool_name}' non installato"
                if self.skip_missing:
                    print(f"  SALTATO: {msg}")
                    logger.warning(f"  {msg}")
                    self.result.errors.append(str(e))
                else:
                    raise

            except Exception as e:
                msg = f"Errore in {tool_name}: {e}"
                logger.error(f"  {msg}")
                self.result.errors.append(msg)
                print(f"  ERRORE: {e}")

            print()

        self.result.end_time = time.time()
        return self.result

    def check_tools(self):
        """Verifica quali tool sono installati e quali mancano."""
        print("\n  Verifica tool installati:")
        print(f"  {'─'*40}")

        installed = []
        missing = []

        for name in self.pipeline:
            if name not in self._tools:
                continue

            tool = self._tools[name]
            if hasattr(tool, "is_installed") and tool.is_installed():
                installed.append(name)
                print(f"  [OK] {name}")
            else:
                missing.append(name)
                print(f"  [--] {name} (non installato)")

        print(f"  {'─'*40}")
        print(f"  Installati: {len(installed)}/{len(installed) + len(missing)}")
        if missing:
            print(f"  Mancanti: {', '.join(missing)}")
            print(f"  Lancia ./install_tools.sh per installarli")
        print()

        return installed, missing
