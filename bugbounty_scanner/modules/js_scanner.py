"""
JavaScript Scanner Module.

Analizza i file JavaScript del target per estrarre:
- Endpoint API nascosti
- Secret/API key hardcoded
- Token e credenziali
- URL interni e path
- Commenti con informazioni sensibili
"""

import logging
import re
from urllib.parse import urlparse, urljoin
from concurrent.futures import ThreadPoolExecutor, as_completed

from bugbounty_scanner.config import (
    DEFAULT_TIMEOUT,
    SEVERITY_HIGH,
    SEVERITY_MEDIUM,
    SEVERITY_LOW,
    SEVERITY_INFO,
)
from bugbounty_scanner.scanner import Finding
from bugbounty_scanner.modules.secret_verifier import verify_secret

logger = logging.getLogger("bugbounty_scanner")

# Pattern per secret e API key
SECRET_PATTERNS = {
    "AWS Access Key": r"(?:AKIA|ABIA|ACCA|ASIA)[0-9A-Z]{16}",
    "AWS Secret Key": r"(?:aws_secret_access_key|AWS_SECRET_ACCESS_KEY)\s*[:=]\s*['\"]?([A-Za-z0-9/+=]{40})",
    "Google API Key": r"AIza[0-9A-Za-z\-_]{35}",
    "Google OAuth": r"[0-9]+-[0-9A-Za-z_]{32}\.apps\.googleusercontent\.com",
    "Firebase URL": r"https?://[a-z0-9-]+\.firebaseio\.com",
    "Firebase API Key": r"(?:firebase|FIREBASE).*?['\"]([A-Za-z0-9_-]{39})['\"]",
    "Slack Token": r"xox[baprs]-[0-9]{10,13}-[0-9]{10,13}-[a-zA-Z0-9]{24,34}",
    "Slack Webhook": r"https://hooks\.slack\.com/services/T[a-zA-Z0-9_]{8}/B[a-zA-Z0-9_]{8}/[a-zA-Z0-9_]{24}",
    "GitHub Token": r"(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9_]{36,255}",
    "Stripe Secret Key": r"sk_(?:live|test)_[0-9a-zA-Z]{24,99}",
    "Stripe Publishable Key": r"pk_(?:live|test)_[0-9a-zA-Z]{24,99}",
    "Twilio API Key": r"SK[0-9a-fA-F]{32}",
    "Twilio Account SID": r"AC[a-zA-Z0-9_\-]{32}",
    "Mailgun API Key": r"key-[0-9a-zA-Z]{32}",
    "SendGrid API Key": r"SG\.[0-9A-Za-z\-_]{22}\.[0-9A-Za-z\-_]{43}",
    "JWT Token": r"eyJ[A-Za-z0-9-_]+\.eyJ[A-Za-z0-9-_]+\.[A-Za-z0-9-_]+",
    "Private Key": r"-----BEGIN (?:RSA |EC )?PRIVATE KEY-----",
    "Bearer Token": r"[Bb]earer\s+[A-Za-z0-9\-._~+/]+=*",
    "Basic Auth": r"[Bb]asic\s+[A-Za-z0-9+/]+=+",
    "Generic API Key": r"(?:api[_-]?key|apikey|api[_-]?secret)\s*[:=]\s*['\"]([A-Za-z0-9_\-]{16,64})['\"]",
    "Generic Secret": r"(?:secret|password|passwd|pwd|token|auth)\s*[:=]\s*['\"]([^\s'\"]{8,64})['\"]",
    "Heroku API Key": r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}",
    "S3 Bucket": r"[a-zA-Z0-9._-]+\.s3\.amazonaws\.com|s3://[a-zA-Z0-9._-]+",
}

# Pattern per endpoint API
ENDPOINT_PATTERNS = [
    r'["\'](/api/[^\s"\'<>]+)["\']',
    r'["\'](/v[0-9]+/[^\s"\'<>]+)["\']',
    r'["\'](https?://[^\s"\'<>]+/api/[^\s"\'<>]+)["\']',
    r'["\'](/graphql[^\s"\'<>]*)["\']',
    r'["\'](/rest/[^\s"\'<>]+)["\']',
    r'["\'](/admin[^\s"\'<>]*)["\']',
    r'["\'](/internal[^\s"\'<>]*)["\']',
    r'["\'](/debug[^\s"\'<>]*)["\']',
    r'["\'](/private[^\s"\'<>]*)["\']',
    r'["\'](/hidden[^\s"\'<>]*)["\']',
    r'fetch\s*\(\s*["\']([^\s"\'<>]+)["\']',
    r'axios\.\w+\s*\(\s*["\']([^\s"\'<>]+)["\']',
    r'\$\.(?:get|post|ajax)\s*\(\s*["\']([^\s"\'<>]+)["\']',
    r'XMLHttpRequest.*?open\s*\(\s*["\'][A-Z]+["\']\s*,\s*["\']([^\s"\'<>]+)["\']',
    r'url\s*[:=]\s*["\']([^\s"\'<>]+)["\']',
    r'endpoint\s*[:=]\s*["\']([^\s"\'<>]+)["\']',
    r'baseURL\s*[:=]\s*["\']([^\s"\'<>]+)["\']',
    r'apiUrl\s*[:=]\s*["\']([^\s"\'<>]+)["\']',
]


class JSScanner:
    """Analizza file JavaScript per secret, endpoint e informazioni sensibili."""

    name = "js_scanner"

    def __init__(self, http_session=None, threads=5):
        if http_session:
            self.session = http_session
        else:
            from bugbounty_scanner.http_session import HttpSession
            self.session = HttpSession()
        self.threads = threads

    def run(self, target, scan_result):
        findings = []

        # 1. Trova tutti i file JS nella pagina
        js_urls = self._discover_js_files(target)
        logger.info(f"  [JS Scanner] Trovati {len(js_urls)} file JavaScript")

        if not js_urls:
            return findings

        # 2. Scarica e analizza ogni file JS
        with ThreadPoolExecutor(max_workers=self.threads) as pool:
            futures = {pool.submit(self._analyze_js, url, target): url for url in js_urls}
            for fut in as_completed(futures):
                js_findings = fut.result()
                if js_findings:
                    findings.extend(js_findings)

        return findings

    def _discover_js_files(self, target):
        """Trova tutti i file JavaScript referenziati nella pagina."""
        js_urls = set()
        try:
            resp = self.session.get(target, timeout=DEFAULT_TIMEOUT)
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(resp.text, "html.parser")

            # Tag <script src="...">
            for script in soup.find_all("script", src=True):
                src = script["src"]
                full_url = urljoin(target, src)
                if full_url.endswith(".js") or ".js?" in full_url:
                    js_urls.add(full_url)

            # Cerca anche URL .js nel testo HTML
            js_in_text = re.findall(r'["\'](https?://[^\s"\']+\.js(?:\?[^\s"\']*)?)["\']', resp.text)
            for js_url in js_in_text:
                js_urls.add(js_url)

            # URL relativi
            js_relative = re.findall(r'["\']([^\s"\']+\.js(?:\?[^\s"\']*)?)["\']', resp.text)
            for js_rel in js_relative:
                if not js_rel.startswith(("http://", "https://")):
                    js_urls.add(urljoin(target, js_rel))

        except Exception as e:
            logger.debug(f"  [JS Scanner] Errore discovery: {e}")

        return list(js_urls)

    def _analyze_js(self, js_url, target):
        """Analizza un singolo file JavaScript."""
        findings = []

        try:
            resp = self.session.get(js_url, timeout=DEFAULT_TIMEOUT)
            if resp.status_code != 200:
                return findings
            js_content = resp.text
        except Exception:
            return findings

        if len(js_content) < 50:
            return findings

        # Cerca secret e API key
        for secret_name, pattern in SECRET_PATTERNS.items():
            matches = re.findall(pattern, js_content)
            if matches:
                # Filtra falsi positivi ovvi
                real_matches = [m for m in matches if not self._is_false_positive(m, secret_name)]
                if real_matches:
                    match_value = real_matches[0] if isinstance(real_matches[0], str) else real_matches[0][0]

                    # Verifica se il secret è attivo
                    is_active = verify_secret(secret_name, match_value, js_content)

                    if is_active is False:
                        # Verificato come INATTIVO: non segnalare
                        logger.info(f"  [JS Scanner] {secret_name} inattivo, scartato")
                        continue

                    if is_active is True:
                        status_label = "VERIFICATO ATTIVO"
                        description = (
                            f"Un {secret_name} ATTIVO è stato trovato nel file JavaScript. "
                            f"Questo secret è stato verificato ed è valido."
                        )
                    else:
                        status_label = "Non verificato"
                        description = (
                            f"Un possibile {secret_name} è stato trovato nel file JavaScript. "
                            f"Non è stato possibile verificarne la validità automaticamente."
                        )

                    findings.append(Finding(
                        title=f"Secret trovato in JS: {secret_name} [{status_label}]",
                        severity=SEVERITY_HIGH,
                        url=js_url,
                        description=description,
                        evidence=f"Pattern: {secret_name}\nStato: {status_label}\nMatch: {match_value[:80]}...",
                        remediation=(
                            "Non includere mai secret, API key o token nei file JavaScript. "
                            "Usa variabili di ambiente lato server e proxy le richieste API."
                        ),
                        module=self.name,
                        cwe="CWE-798",
                    ))

        # Cerca endpoint API
        endpoints = set()
        for pattern in ENDPOINT_PATTERNS:
            matches = re.findall(pattern, js_content)
            for match in matches:
                if isinstance(match, tuple):
                    match = match[0]
                match = match.strip()
                if len(match) > 3 and not match.endswith((".js", ".css", ".png", ".jpg", ".svg")):
                    endpoints.add(match)

        if endpoints:
            findings.append(Finding(
                title=f"Endpoint API trovati in JS ({len(endpoints)})",
                severity=SEVERITY_INFO,
                url=js_url,
                description=f"Trovati {len(endpoints)} possibili endpoint API nel file JavaScript.",
                evidence="\n".join(sorted(endpoints)[:30]),
                remediation="Verifica che tutti gli endpoint esposti richiedano autenticazione.",
                module=self.name,
            ))

        # Cerca commenti con informazioni sensibili
        comment_findings = self._check_comments(js_content, js_url)
        findings.extend(comment_findings)

        # Cerca source map
        if "//# sourceMappingURL=" in js_content:
            map_match = re.search(r'//# sourceMappingURL=(\S+)', js_content)
            if map_match:
                map_url = urljoin(js_url, map_match.group(1))
                findings.append(Finding(
                    title="Source Map esposta",
                    severity=SEVERITY_LOW,
                    url=map_url,
                    description=(
                        "Il file JavaScript include un riferimento a una source map. "
                        "Le source map espongono il codice sorgente originale."
                    ),
                    evidence=f"Source map: {map_url}",
                    remediation="Rimuovi le source map in produzione.",
                    module=self.name,
                    cwe="CWE-540",
                ))

        return findings

    def _check_comments(self, js_content, js_url):
        """Cerca commenti con informazioni sensibili."""
        findings = []
        sensitive_comment_patterns = [
            (r'//\s*TODO:?\s*(.+)', "TODO comment"),
            (r'//\s*FIXME:?\s*(.+)', "FIXME comment"),
            (r'//\s*HACK:?\s*(.+)', "HACK comment"),
            (r'//\s*BUG:?\s*(.+)', "BUG comment"),
            (r'//\s*XXX:?\s*(.+)', "XXX comment"),
            (r'/\*[\s\S]*?(?:password|secret|admin|internal|private|credential)[\s\S]*?\*/', "Sensitive comment"),
        ]

        for pattern, comment_type in sensitive_comment_patterns:
            matches = re.findall(pattern, js_content, re.IGNORECASE)
            if matches:
                findings.append(Finding(
                    title=f"Commento sensibile in JS: {comment_type}",
                    severity=SEVERITY_INFO,
                    url=js_url,
                    description=f"Trovati {len(matches)} commenti di tipo '{comment_type}' nel JavaScript.",
                    evidence="\n".join(m[:100] if isinstance(m, str) else str(m)[:100] for m in matches[:5]),
                    module=self.name,
                ))

        return findings

    @staticmethod
    def _is_false_positive(match, secret_name):
        """Filtra falsi positivi comuni."""
        if isinstance(match, tuple):
            match = match[0] if match else ""
        match = str(match)

        # Troppo corto
        if len(match) < 8:
            return True

        # Placeholder ovvi
        placeholders = [
            "xxxxxxxx", "your_api_key", "INSERT_KEY_HERE", "REPLACE_ME",
            "example", "test", "demo", "sample", "placeholder", "changeme",
            "00000000", "11111111", "abcdefgh", "12345678",
        ]
        match_lower = match.lower()
        return any(p in match_lower for p in placeholders)
