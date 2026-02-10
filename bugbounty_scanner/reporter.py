"""Sistema di reportistica: genera report in JSON, HTML e Markdown."""

import json
import os
from datetime import datetime

from jinja2 import Template

from bugbounty_scanner.scanner import ScanResult


HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="it">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Report Scansione Bug Bounty - {{ result.target }}</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: 'Segoe UI', Tahoma, sans-serif; background: #0d1117; color: #c9d1d9; padding: 20px; }
  .container { max-width: 1100px; margin: 0 auto; }
  h1 { color: #58a6ff; margin-bottom: 10px; }
  h2 { color: #58a6ff; margin: 25px 0 10px; border-bottom: 1px solid #30363d; padding-bottom: 8px; }
  .summary { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 15px; margin: 20px 0; }
  .summary-card { background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 15px; text-align: center; }
  .summary-card .value { font-size: 2em; font-weight: bold; }
  .critical { color: #f85149; }
  .high { color: #db6d28; }
  .medium { color: #d29922; }
  .low { color: #58a6ff; }
  .info { color: #8b949e; }
  .finding { background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 15px; margin: 10px 0; }
  .finding-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; }
  .finding-title { font-size: 1.1em; font-weight: bold; }
  .badge { padding: 3px 10px; border-radius: 12px; font-size: 0.8em; font-weight: bold; color: #fff; }
  .badge-CRITICAL { background: #f85149; }
  .badge-HIGH { background: #db6d28; }
  .badge-MEDIUM { background: #d29922; }
  .badge-LOW { background: #58a6ff; }
  .badge-INFO { background: #8b949e; }
  .field { margin: 5px 0; }
  .field-label { font-weight: bold; color: #8b949e; }
  pre { background: #0d1117; border: 1px solid #30363d; padding: 10px; border-radius: 6px; overflow-x: auto; margin: 5px 0; font-size: 0.9em; }
  .meta { color: #8b949e; font-size: 0.9em; margin-bottom: 20px; }
</style>
</head>
<body>
<div class="container">
  <h1>Report Scansione Bug Bounty</h1>
  <p class="meta">Target: {{ result.target }} | Data: {{ timestamp }} | Durata: {{ "%.2f"|format(result.duration) }}s</p>

  <h2>Riepilogo</h2>
  <div class="summary">
    <div class="summary-card">
      <div class="value">{{ result.findings|length }}</div>
      <div>Problemi Totali</div>
    </div>
    <div class="summary-card">
      <div class="value critical">{{ severity_counts.get('CRITICAL', 0) }}</div>
      <div>Critici</div>
    </div>
    <div class="summary-card">
      <div class="value high">{{ severity_counts.get('HIGH', 0) }}</div>
      <div>Alti</div>
    </div>
    <div class="summary-card">
      <div class="value medium">{{ severity_counts.get('MEDIUM', 0) }}</div>
      <div>Medi</div>
    </div>
    <div class="summary-card">
      <div class="value low">{{ severity_counts.get('LOW', 0) }}</div>
      <div>Bassi</div>
    </div>
    <div class="summary-card">
      <div class="value info">{{ severity_counts.get('INFO', 0) }}</div>
      <div>Info</div>
    </div>
  </div>

  {% if result.subdomains %}
  <h2>Sottodomini Scoperti ({{ result.subdomains|length }})</h2>
  <pre>{{ result.subdomains|join('\\n') }}</pre>
  {% endif %}

  {% if result.open_ports %}
  <h2>Porte Aperte</h2>
  <pre>{{ result.open_ports|join(', ') }}</pre>
  {% endif %}

  {% if result.technologies %}
  <h2>Tecnologie Rilevate</h2>
  <pre>{{ result.technologies|join('\\n') }}</pre>
  {% endif %}

  <h2>Vulnerabilita Trovate ({{ result.findings|length }})</h2>
  {% for finding in findings_sorted %}
  <div class="finding">
    <div class="finding-header">
      <span class="finding-title">{{ finding.title }}</span>
      <span class="badge badge-{{ finding.severity }}">{{ finding.severity }}</span>
    </div>
    <div class="field"><span class="field-label">URL:</span> {{ finding.url }}</div>
    <div class="field"><span class="field-label">Descrizione:</span> {{ finding.description }}</div>
    {% if finding.evidence %}
    <div class="field"><span class="field-label">Evidenza:</span><pre>{{ finding.evidence }}</pre></div>
    {% endif %}
    {% if finding.remediation %}
    <div class="field"><span class="field-label">Rimedio:</span> {{ finding.remediation }}</div>
    {% endif %}
    {% if finding.cwe %}
    <div class="field"><span class="field-label">CWE:</span> {{ finding.cwe }}</div>
    {% endif %}
    <div class="field"><span class="field-label">Modulo:</span> {{ finding.module }}</div>
  </div>
  {% endfor %}

  {% if result.errors %}
  <h2>Errori</h2>
  <pre>{{ result.errors|join('\\n') }}</pre>
  {% endif %}
</div>
</body>
</html>
"""


class Reporter:
    """Genera report di scansione in vari formati."""

    SEVERITY_ORDER = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"]

    def __init__(self, scan_result: ScanResult, output_dir: str = "reports"):
        self.result = scan_result
        self.output_dir = output_dir
        self.timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        os.makedirs(output_dir, exist_ok=True)

    def _sorted_findings(self):
        """Ordina i risultati per gravita."""
        return sorted(
            self.result.findings,
            key=lambda f: self.SEVERITY_ORDER.index(f.severity)
            if f.severity in self.SEVERITY_ORDER
            else 99,
        )

    def _severity_counts(self):
        counts = {}
        for f in self.result.findings:
            counts[f.severity] = counts.get(f.severity, 0) + 1
        return counts

    def generate_json(self, filename=None) -> str:
        """Genera report in formato JSON."""
        filename = filename or f"report_{self._safe_domain()}.json"
        filepath = os.path.join(self.output_dir, filename)

        data = {
            "target": self.result.target,
            "timestamp": self.timestamp,
            "duration_seconds": round(self.result.duration, 2),
            "summary": self._severity_counts(),
            "subdomains": self.result.subdomains,
            "open_ports": self.result.open_ports,
            "technologies": self.result.technologies,
            "findings": [f.to_dict() for f in self._sorted_findings()],
            "errors": self.result.errors,
        }

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        return filepath

    def generate_html(self, filename=None) -> str:
        """Genera report in formato HTML."""
        filename = filename or f"report_{self._safe_domain()}.html"
        filepath = os.path.join(self.output_dir, filename)

        template = Template(HTML_TEMPLATE)
        html = template.render(
            result=self.result,
            findings_sorted=self._sorted_findings(),
            severity_counts=self._severity_counts(),
            timestamp=self.timestamp,
        )

        with open(filepath, "w", encoding="utf-8") as f:
            f.write(html)

        return filepath

    def generate_markdown(self, filename=None) -> str:
        """Genera report in formato Markdown."""
        filename = filename or f"report_{self._safe_domain()}.md"
        filepath = os.path.join(self.output_dir, filename)

        counts = self._severity_counts()
        lines = [
            f"# Report Scansione Bug Bounty",
            f"",
            f"**Target:** {self.result.target}",
            f"**Data:** {self.timestamp}",
            f"**Durata:** {self.result.duration:.2f}s",
            f"",
            f"## Riepilogo",
            f"",
            f"| Gravita | Conteggio |",
            f"|---------|-----------|",
        ]
        for sev in self.SEVERITY_ORDER:
            lines.append(f"| {sev} | {counts.get(sev, 0)} |")

        lines.append(f"| **TOTALE** | **{len(self.result.findings)}** |")
        lines.append("")

        if self.result.subdomains:
            lines.append(f"## Sottodomini ({len(self.result.subdomains)})")
            lines.append("")
            for sub in self.result.subdomains:
                lines.append(f"- `{sub}`")
            lines.append("")

        if self.result.open_ports:
            lines.append(f"## Porte Aperte")
            lines.append("")
            lines.append(f"`{', '.join(str(p) for p in self.result.open_ports)}`")
            lines.append("")

        if self.result.technologies:
            lines.append(f"## Tecnologie Rilevate")
            lines.append("")
            for tech in self.result.technologies:
                lines.append(f"- {tech}")
            lines.append("")

        lines.append("## Vulnerabilita")
        lines.append("")

        for i, finding in enumerate(self._sorted_findings(), 1):
            lines.append(f"### {i}. [{finding.severity}] {finding.title}")
            lines.append("")
            lines.append(f"- **URL:** `{finding.url}`")
            lines.append(f"- **Descrizione:** {finding.description}")
            if finding.evidence:
                lines.append(f"- **Evidenza:**")
                lines.append(f"  ```")
                lines.append(f"  {finding.evidence}")
                lines.append(f"  ```")
            if finding.remediation:
                lines.append(f"- **Rimedio:** {finding.remediation}")
            if finding.cwe:
                lines.append(f"- **CWE:** {finding.cwe}")
            lines.append(f"- **Modulo:** {finding.module}")
            lines.append("")

        if self.result.errors:
            lines.append("## Errori")
            lines.append("")
            for err in self.result.errors:
                lines.append(f"- {err}")
            lines.append("")

        with open(filepath, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

        return filepath

    def generate_all(self):
        """Genera report in tutti i formati."""
        paths = {
            "json": self.generate_json(),
            "html": self.generate_html(),
            "markdown": self.generate_markdown(),
        }
        return paths

    def _safe_domain(self):
        """Genera un nome file sicuro dal dominio."""
        from urllib.parse import urlparse
        domain = urlparse(self.result.target).netloc
        return domain.replace(":", "_").replace("/", "_")

    def print_summary(self):
        """Stampa un riepilogo sulla console."""
        counts = self._severity_counts()
        total = len(self.result.findings)

        print(f"\n{'='*60}")
        print(f"  RIEPILOGO SCANSIONE - {self.result.target}")
        print(f"{'='*60}")
        print(f"  Durata: {self.result.duration:.2f}s")
        print(f"  Problemi trovati: {total}")
        print()

        for sev in self.SEVERITY_ORDER:
            count = counts.get(sev, 0)
            if count > 0:
                print(f"  [{sev:8s}] {count}")

        if self.result.subdomains:
            print(f"\n  Sottodomini scoperti: {len(self.result.subdomains)}")
        if self.result.open_ports:
            print(f"  Porte aperte: {', '.join(str(p) for p in self.result.open_ports)}")
        if self.result.technologies:
            print(f"  Tecnologie: {', '.join(self.result.technologies[:5])}")

        print(f"{'='*60}\n")
