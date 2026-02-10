"""
Deep Crawler Module.

Scopre automaticamente tutte le pagine, form, endpoint e parametri
del target navigando ricorsivamente il sito.
"""

import logging
import re
from collections import deque
from urllib.parse import urlparse, urljoin, parse_qs

from bs4 import BeautifulSoup

from bugbounty_scanner.config import DEFAULT_TIMEOUT, SEVERITY_INFO
from bugbounty_scanner.scanner import Finding

logger = logging.getLogger("bugbounty_scanner")


class CrawlerModule:
    """Crawla il sito per scoprire pagine, form, endpoint e parametri."""

    name = "crawler"

    def __init__(self, http_session=None, max_pages=100, max_depth=3):
        if http_session:
            self.session = http_session
        else:
            from bugbounty_scanner.http_session import HttpSession
            self.session = HttpSession()
        self.max_pages = max_pages
        self.max_depth = max_depth

    def run(self, target, scan_result):
        findings = []
        logger.info(f"  [Crawler] Crawling {target} (max {self.max_pages} pagine, depth {self.max_depth})")

        crawl_result = self._crawl(target)

        # Salva i risultati nel scan_result per gli altri moduli
        scan_result.crawled_urls = crawl_result["urls"]
        scan_result.discovered_forms = crawl_result["forms"]
        scan_result.discovered_params = crawl_result["params"]
        scan_result.discovered_emails = crawl_result["emails"]

        if crawl_result["urls"]:
            findings.append(Finding(
                title=f"Pagine scoperte: {len(crawl_result['urls'])}",
                severity=SEVERITY_INFO,
                url=target,
                description=f"Il crawler ha scoperto {len(crawl_result['urls'])} pagine uniche.",
                evidence="\n".join(sorted(crawl_result["urls"])[:30]),
                module=self.name,
            ))

        if crawl_result["forms"]:
            findings.append(Finding(
                title=f"Form trovati: {len(crawl_result['forms'])}",
                severity=SEVERITY_INFO,
                url=target,
                description=f"Trovati {len(crawl_result['forms'])} form HTML (potenziali vettori di attacco).",
                evidence="\n".join(
                    f"{f['method']} {f['action']} - campi: {', '.join(f['fields'][:5])}"
                    for f in crawl_result["forms"][:10]
                ),
                module=self.name,
            ))

        if crawl_result["params"]:
            findings.append(Finding(
                title=f"Parametri URL scoperti: {len(crawl_result['params'])}",
                severity=SEVERITY_INFO,
                url=target,
                description="Parametri query string trovati durante il crawling.",
                evidence="\n".join(sorted(crawl_result["params"])[:30]),
                module=self.name,
            ))

        if crawl_result["emails"]:
            findings.append(Finding(
                title=f"Email trovate: {len(crawl_result['emails'])}",
                severity=SEVERITY_INFO,
                url=target,
                description="Indirizzi email scoperti nelle pagine del sito.",
                evidence="\n".join(sorted(crawl_result["emails"])),
                module=self.name,
            ))

        return findings

    def _crawl(self, start_url):
        """Crawla il sito partendo dall'URL iniziale."""
        parsed_start = urlparse(start_url)
        base_domain = parsed_start.netloc

        visited = set()
        queue = deque([(start_url, 0)])  # (url, depth)

        result = {
            "urls": set(),
            "forms": [],
            "params": set(),
            "emails": set(),
        }

        while queue and len(visited) < self.max_pages:
            url, depth = queue.popleft()

            # Normalizza URL
            url = url.split("#")[0]  # Rimuovi fragment
            if url in visited:
                continue
            if depth > self.max_depth:
                continue

            visited.add(url)

            try:
                resp = self.session.get(url, timeout=DEFAULT_TIMEOUT, allow_redirects=True)
                if "text/html" not in resp.headers.get("Content-Type", ""):
                    continue
            except Exception:
                continue

            result["urls"].add(url)

            # Estrai parametri dall'URL
            qs = parse_qs(urlparse(url).query)
            for param_name in qs:
                result["params"].add(f"{param_name} ({url.split('?')[0]})")

            try:
                soup = BeautifulSoup(resp.text, "html.parser")
            except Exception:
                continue

            # Estrai link
            for tag in soup.find_all(["a", "link"], href=True):
                href = tag["href"]
                full_url = urljoin(url, href)
                full_parsed = urlparse(full_url)

                # Solo lo stesso dominio
                if full_parsed.netloc == base_domain:
                    clean_url = full_url.split("#")[0]
                    if clean_url not in visited:
                        queue.append((clean_url, depth + 1))

            # Estrai form
            for form in soup.find_all("form"):
                action = form.get("action", "")
                method = form.get("method", "GET").upper()
                full_action = urljoin(url, action) if action else url

                fields = []
                for inp in form.find_all(["input", "textarea", "select"]):
                    name = inp.get("name")
                    if name:
                        fields.append(name)
                        result["params"].add(f"{name} ({full_action})")

                if fields:
                    result["forms"].append({
                        "action": full_action,
                        "method": method,
                        "fields": fields,
                        "page": url,
                    })

            # Estrai email
            emails = re.findall(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', resp.text)
            result["emails"].update(emails)

            # Estrai URL da JavaScript inline
            js_urls = re.findall(r'["\'](https?://[^\s"\'<>]+)["\']', resp.text)
            for js_url in js_urls:
                js_parsed = urlparse(js_url)
                if js_parsed.netloc == base_domain and js_url not in visited:
                    queue.append((js_url, depth + 1))

        logger.info(f"  [Crawler] Crawlate {len(visited)} pagine, trovati {len(result['forms'])} form")

        # Converti set in list per serializzazione
        result["urls"] = list(result["urls"])
        result["params"] = list(result["params"])
        result["emails"] = list(result["emails"])

        return result
