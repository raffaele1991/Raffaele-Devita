"""
Parser per programmi Bug Bounty.

Estrae automaticamente scope, out-of-scope, regole e reward
dalle pagine dei programmi su Intigriti, HackerOne e Bugcrowd.

Supporta anche file scope manuali (testo con un dominio per riga).
"""

import json
import logging
import re
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger("bugbounty_scanner")


class ProgramInfo:
    """Contiene tutte le informazioni estratte da un programma bug bounty."""

    def __init__(self):
        self.platform = ""           # intigriti, hackerone, bugcrowd
        self.program_name = ""
        self.program_url = ""
        self.in_scope_domains = []   # domini in scope (*.example.com, api.example.com)
        self.in_scope_urls = []      # URL specifici in scope
        self.in_scope_types = []     # tipi: web, api, mobile, ecc.
        self.out_of_scope_domains = []
        self.out_of_scope_urls = []
        self.out_of_scope_patterns = []  # pattern da evitare
        self.rules = []              # regole del programma
        self.rewards = {}            # tabella reward per gravità
        self.vuln_exclusions = []    # vulnerabilità fuori scope (es: "self-xss")
        self.raw_scope_text = ""     # testo raw dello scope

    def is_in_scope(self, url_or_domain):
        """Verifica se un URL/dominio è in scope."""
        target = url_or_domain.lower().strip()

        # Rimuovi schema se presente
        if "://" in target:
            target = urlparse(target).netloc

        # Rimuovi porta
        if ":" in target:
            target = target.split(":")[0]

        # Check out-of-scope prima (ha priorità)
        for oos in self.out_of_scope_domains:
            oos = oos.lower().strip()
            if oos.startswith("*."):
                # Wildcard: *.staging.example.com blocca tutto sotto staging
                base = oos[2:]
                if target == base or target.endswith("." + base):
                    return False
            elif target == oos:
                return False

        for pattern in self.out_of_scope_patterns:
            if re.search(pattern, target, re.IGNORECASE):
                return False

        # Check in-scope
        if not self.in_scope_domains:
            return True  # se non c'è scope definito, permetti tutto

        for ins in self.in_scope_domains:
            ins = ins.lower().strip()
            if ins.startswith("*."):
                base = ins[2:]
                if target == base or target.endswith("." + base):
                    return True
            elif target == ins:
                return True

        return False

    def summary(self):
        """Stampa un riepilogo del programma."""
        lines = []
        lines.append(f"\n  {'='*55}")
        lines.append(f"  PROGRAMMA: {self.program_name}")
        lines.append(f"  Piattaforma: {self.platform}")
        lines.append(f"  URL: {self.program_url}")
        lines.append(f"  {'='*55}")

        if self.in_scope_domains:
            lines.append(f"\n  IN SCOPE ({len(self.in_scope_domains)} domini):")
            for d in self.in_scope_domains:
                lines.append(f"    [+] {d}")

        if self.in_scope_types:
            lines.append(f"\n  TIPI IN SCOPE: {', '.join(self.in_scope_types)}")

        if self.out_of_scope_domains:
            lines.append(f"\n  OUT OF SCOPE ({len(self.out_of_scope_domains)} domini):")
            for d in self.out_of_scope_domains:
                lines.append(f"    [-] {d}")

        if self.vuln_exclusions:
            lines.append(f"\n  VULNERABILITA' ESCLUSE:")
            for v in self.vuln_exclusions:
                lines.append(f"    [x] {v}")

        if self.rewards:
            lines.append(f"\n  REWARD:")
            for sev, amount in self.rewards.items():
                lines.append(f"    {sev}: {amount}")

        if self.rules:
            lines.append(f"\n  REGOLE ({len(self.rules)}):")
            for r in self.rules[:10]:
                lines.append(f"    - {r[:100]}")

        lines.append(f"  {'='*55}\n")
        return "\n".join(lines)


class ProgramParser:
    """Parser principale che detecta la piattaforma e estrae le info."""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers["User-Agent"] = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
        )

    def parse(self, source) -> ProgramInfo:
        """
        Parsa un programma bug bounty da URL o file.

        Args:
            source: URL del programma o path a un file scope.

        Returns:
            ProgramInfo con scope e regole estratte.
        """
        info = ProgramInfo()

        # Se è un file locale
        if not source.startswith("http"):
            return self._parse_scope_file(source)

        info.program_url = source

        # Detecta la piattaforma
        if "hackerone.com" in source:
            info.platform = "hackerone"
            return self._parse_hackerone(source, info)
        elif "intigriti.com" in source:
            info.platform = "intigriti"
            return self._parse_intigriti(source, info)
        elif "bugcrowd.com" in source:
            info.platform = "bugcrowd"
            return self._parse_bugcrowd(source, info)
        else:
            # Prova a parsare come pagina generica
            info.platform = "custom"
            return self._parse_generic(source, info)

    def _fetch_page(self, url):
        """Scarica una pagina e ritorna il testo HTML."""
        try:
            resp = self.session.get(url, timeout=15)
            resp.raise_for_status()
            return resp.text
        except requests.RequestException as e:
            logger.error(f"  Errore nel scaricare {url}: {e}")
            return ""

    # ==================== HACKERONE ====================

    def _parse_hackerone(self, url, info):
        """Parsa un programma HackerOne."""
        # Estrai slug del programma
        match = re.search(r"hackerone\.com/([^/?#]+)", url)
        if match:
            slug = match.group(1)
            info.program_name = slug

        html = self._fetch_page(url)
        if not html:
            return info

        soup = BeautifulSoup(html, "html.parser")
        text = soup.get_text(separator="\n")
        info.raw_scope_text = text

        # Cerca sezione scope
        self._extract_domains_from_text(text, info)
        self._extract_rules_from_text(text, info)
        self._extract_vuln_exclusions(text, info)

        # HackerOne API pubblica (se disponibile)
        api_url = f"https://hackerone.com/programs/{slug}/policy_scopes.json"
        try:
            resp = self.session.get(api_url, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                self._parse_hackerone_api(data, info)
        except Exception:
            pass

        return info

    def _parse_hackerone_api(self, data, info):
        """Parsa la risposta API di HackerOne per lo scope."""
        if not isinstance(data, dict):
            return

        scopes = data.get("data", [])
        if not isinstance(scopes, list):
            return

        for scope in scopes:
            attrs = scope.get("attributes", {})
            asset_id = attrs.get("asset_identifier", "")
            asset_type = attrs.get("asset_type", "")
            eligible = attrs.get("eligible_for_bounty", False)
            eligible_submission = attrs.get("eligible_for_submission", True)

            if not asset_id:
                continue

            if asset_type in ("URL", "DOMAIN", "WILDCARD"):
                if eligible_submission:
                    info.in_scope_domains.append(asset_id)
                    if asset_type not in info.in_scope_types:
                        info.in_scope_types.append(asset_type.lower())

    # ==================== INTIGRITI ====================

    def _parse_intigriti(self, url, info):
        """Parsa un programma Intigriti."""
        match = re.search(r"intigriti\.com/(?:researcher/)?programs/([^/?#]+)/([^/?#]+)", url)
        if match:
            info.program_name = f"{match.group(1)}/{match.group(2)}"

        html = self._fetch_page(url)
        if not html:
            return info

        soup = BeautifulSoup(html, "html.parser")
        text = soup.get_text(separator="\n")
        info.raw_scope_text = text

        self._extract_domains_from_text(text, info)
        self._extract_rules_from_text(text, info)
        self._extract_vuln_exclusions(text, info)

        return info

    # ==================== BUGCROWD ====================

    def _parse_bugcrowd(self, url, info):
        """Parsa un programma Bugcrowd."""
        match = re.search(r"bugcrowd\.com/([^/?#]+)", url)
        if match:
            info.program_name = match.group(1)

        html = self._fetch_page(url)
        if not html:
            return info

        soup = BeautifulSoup(html, "html.parser")
        text = soup.get_text(separator="\n")
        info.raw_scope_text = text

        self._extract_domains_from_text(text, info)
        self._extract_rules_from_text(text, info)
        self._extract_vuln_exclusions(text, info)

        return info

    # ==================== GENERICA ====================

    def _parse_generic(self, url, info):
        """Prova a parsare qualsiasi pagina web per estrarre scope."""
        html = self._fetch_page(url)
        if not html:
            return info

        soup = BeautifulSoup(html, "html.parser")
        text = soup.get_text(separator="\n")
        info.raw_scope_text = text
        info.program_name = soup.title.string if soup.title else url

        self._extract_domains_from_text(text, info)
        self._extract_rules_from_text(text, info)
        self._extract_vuln_exclusions(text, info)

        return info

    # ==================== FILE SCOPE ====================

    def _parse_scope_file(self, filepath):
        """Parsa un file di testo con scope (un dominio per riga)."""
        info = ProgramInfo()
        info.platform = "file"
        info.program_name = filepath

        try:
            with open(filepath, "r") as f:
                content = f.read()
        except IOError as e:
            logger.error(f"  Errore lettura file scope: {e}")
            return info

        in_scope_section = True
        for line in content.splitlines():
            line = line.strip()

            if not line or line.startswith("#"):
                # Detecta sezioni
                if "out" in line.lower() and "scope" in line.lower():
                    in_scope_section = False
                elif "in" in line.lower() and "scope" in line.lower():
                    in_scope_section = True
                continue

            # È un dominio/URL valido?
            if self._looks_like_domain(line):
                if in_scope_section:
                    info.in_scope_domains.append(line)
                else:
                    info.out_of_scope_domains.append(line)

        return info

    # ==================== UTILITY ====================

    def _extract_domains_from_text(self, text, info):
        """Estrae domini e URL dal testo della pagina del programma."""
        # Pattern per domini
        domain_pattern = re.compile(
            r'(?:\*\.)?(?:[a-zA-Z0-9](?:[a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?\.)+'
            r'[a-zA-Z]{2,}',
            re.MULTILINE,
        )

        # Pattern per URL
        url_pattern = re.compile(
            r'https?://[^\s<>"\')\]]+',
            re.MULTILINE,
        )

        # Cerca sezioni in-scope e out-of-scope nel testo
        lines = text.split("\n")
        current_section = None  # "in" o "out"

        in_scope_keywords = [
            "in scope", "in-scope", "inscope", "scope target",
            "eligible", "target", "asset",
        ]
        out_scope_keywords = [
            "out of scope", "out-of-scope", "outofscope", "out scope",
            "not eligible", "excluded", "exclusion",
        ]

        for i, line in enumerate(lines):
            line_lower = line.lower().strip()

            # Detecta sezione
            if any(kw in line_lower for kw in out_scope_keywords):
                current_section = "out"
                continue
            elif any(kw in line_lower for kw in in_scope_keywords):
                current_section = "in"
                continue

            # Estrai domini dalla riga
            domains = domain_pattern.findall(line)
            urls = url_pattern.findall(line)

            for domain in domains:
                domain = domain.strip().rstrip(".")
                if not self._is_common_word(domain):
                    if current_section == "out":
                        if domain not in info.out_of_scope_domains:
                            info.out_of_scope_domains.append(domain)
                    elif current_section == "in":
                        if domain not in info.in_scope_domains:
                            info.in_scope_domains.append(domain)
                    # Se non siamo in nessuna sezione, prova a indovinare
                    elif self._looks_like_target(domain):
                        if domain not in info.in_scope_domains:
                            info.in_scope_domains.append(domain)

            for url in urls:
                url = url.rstrip(".,;)")
                parsed = urlparse(url)
                if current_section == "out":
                    if url not in info.out_of_scope_urls:
                        info.out_of_scope_urls.append(url)
                elif current_section == "in":
                    if url not in info.in_scope_urls:
                        info.in_scope_urls.append(url)

    def _extract_rules_from_text(self, text, info):
        """Estrae le regole del programma dal testo."""
        rule_keywords = [
            "do not", "don't", "must not", "should not", "never",
            "prohibited", "forbidden", "not allowed", "avoid",
            "please do not", "rate limit", "no automated",
            "responsible disclosure", "disclosure policy",
            "social engineering", "physical", "denial of service",
            "dos attack",
        ]

        for line in text.split("\n"):
            line = line.strip()
            if len(line) < 10 or len(line) > 300:
                continue
            line_lower = line.lower()
            if any(kw in line_lower for kw in rule_keywords):
                if line not in info.rules:
                    info.rules.append(line)

    def _extract_vuln_exclusions(self, text, info):
        """Estrae le vulnerabilità escluse dallo scope."""
        exclusion_patterns = [
            "self-xss", "self xss",
            "logout csrf", "login csrf",
            "clickjacking on",
            "missing security headers",
            "rate limiting",
            "email enumeration",
            "username enumeration",
            "stack trace",
            "verbose error",
            "autocomplete",
            "tabnabbing",
            "text injection",
            "content spoofing",
            "host header injection",
            "cookie without",
            "mixed content",
            "information disclosure in",
            "spf", "dmarc", "dkim",
            "open redirect on login",
            "brute force",
        ]

        text_lower = text.lower()
        for pattern in exclusion_patterns:
            if pattern in text_lower:
                if pattern not in info.vuln_exclusions:
                    info.vuln_exclusions.append(pattern)

    @staticmethod
    def _looks_like_domain(text):
        """Verifica se un testo sembra un dominio."""
        text = text.strip().lstrip("*.")
        return bool(re.match(
            r'^[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?'
            r'(\.[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?)*'
            r'\.[a-zA-Z]{2,}$',
            text,
        ))

    @staticmethod
    def _looks_like_target(domain):
        """Verifica se un dominio sembra un target reale (non un sito generico)."""
        generic = [
            "google.com", "facebook.com", "twitter.com", "github.com",
            "youtube.com", "linkedin.com", "example.com", "mozilla.org",
            "w3.org", "wikipedia.org", "cloudflare.com", "amazonaws.com",
        ]
        return domain.lower() not in generic

    @staticmethod
    def _is_common_word(text):
        """Filtra falsi positivi che sembrano domini ma non lo sono."""
        false_positives = [
            "e.g.", "i.e.", "etc.", "a.m.", "p.m.",
        ]
        return text.lower() in false_positives
