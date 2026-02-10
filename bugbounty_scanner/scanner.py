"""Core scanner engine that orchestrates all vulnerability modules."""

import time
import logging
from dataclasses import dataclass, field
from typing import Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse

from bugbounty_scanner.config import MAX_THREADS, DELAY_BETWEEN_REQUESTS

logger = logging.getLogger("bugbounty_scanner")


@dataclass
class Finding:
    """Represents a single vulnerability finding."""

    title: str
    severity: str
    url: str
    description: str
    evidence: str = ""
    remediation: str = ""
    module: str = ""
    cwe: str = ""

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "severity": self.severity,
            "url": self.url,
            "description": self.description,
            "evidence": self.evidence,
            "remediation": self.remediation,
            "module": self.module,
            "cwe": self.cwe,
        }


@dataclass
class ScanResult:
    """Aggregated scan results for a target."""

    target: str
    start_time: float = 0.0
    end_time: float = 0.0
    findings: list = field(default_factory=list)
    subdomains: list = field(default_factory=list)
    open_ports: list = field(default_factory=list)
    technologies: list = field(default_factory=list)
    errors: list = field(default_factory=list)

    @property
    def duration(self) -> float:
        return self.end_time - self.start_time

    @property
    def summary(self) -> dict:
        severity_counts = {}
        for f in self.findings:
            severity_counts[f.severity] = severity_counts.get(f.severity, 0) + 1
        return {
            "target": self.target,
            "duration_seconds": round(self.duration, 2),
            "total_findings": len(self.findings),
            "by_severity": severity_counts,
            "subdomains_found": len(self.subdomains),
            "open_ports": len(self.open_ports),
            "technologies_detected": self.technologies,
        }


class Scanner:
    """Main scanner engine that coordinates all scanning modules."""

    def __init__(
        self,
        target: str,
        threads: int = MAX_THREADS,
        delay: float = DELAY_BETWEEN_REQUESTS,
        modules: Optional[list] = None,
        verbose: bool = False,
    ):
        self.target = self._normalize_target(target)
        self.domain = urlparse(self.target).netloc
        self.threads = threads
        self.delay = delay
        self.enabled_modules = modules
        self.verbose = verbose
        self.result = ScanResult(target=self.target)
        self._modules = []

    @staticmethod
    def _normalize_target(target: str) -> str:
        """Ensure target has a scheme."""
        if not target.startswith(("http://", "https://")):
            target = "https://" + target
        return target.rstrip("/")

    def register_module(self, module):
        """Register a scanning module."""
        self._modules.append(module)

    def _should_run(self, module_name: str) -> bool:
        """Check if a module should run based on enabled_modules filter."""
        if self.enabled_modules is None:
            return True
        return module_name in self.enabled_modules

    def run(self) -> ScanResult:
        """Execute all registered scanning modules."""
        self.result.start_time = time.time()
        logger.info(f"Starting scan on {self.target}")

        for mod in self._modules:
            mod_name = mod.name if hasattr(mod, "name") else mod.__class__.__name__
            if not self._should_run(mod_name):
                logger.info(f"Skipping module: {mod_name}")
                continue

            logger.info(f"Running module: {mod_name}")
            try:
                findings = mod.run(self.target, self.result)
                if findings:
                    self.result.findings.extend(findings)
                    logger.info(
                        f"  [{mod_name}] Found {len(findings)} issue(s)"
                    )
                else:
                    logger.info(f"  [{mod_name}] No issues found")
            except Exception as e:
                err_msg = f"Module {mod_name} failed: {e}"
                logger.error(err_msg)
                self.result.errors.append(err_msg)

            if self.delay > 0:
                time.sleep(self.delay)

        self.result.end_time = time.time()
        logger.info(
            f"Scan completed in {self.result.duration:.2f}s - "
            f"{len(self.result.findings)} findings"
        )
        return self.result
