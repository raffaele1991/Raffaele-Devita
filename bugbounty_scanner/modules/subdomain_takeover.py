"""
Subdomain Takeover Detection Module.

Cerca sottodomini con CNAME che puntano a servizi non più configurati.
Se un CNAME punta a GitHub Pages, Heroku, S3, ecc. e il servizio risponde
con una pagina "non trovato", il sottodominio è vulnerabile a takeover.

Paga: MEDIUM-HIGH su quasi tutti i programmi bug bounty.
"""

import logging
import re
import subprocess
import socket

import requests

from bugbounty_scanner.config import SEVERITY_HIGH, SEVERITY_MEDIUM, DEFAULT_USER_AGENT
from bugbounty_scanner.scanner import Finding

logger = logging.getLogger("bugbounty_scanner")


# Servizi vulnerabili: (pattern CNAME, fingerprint nella risposta HTTP, nome servizio)
VULNERABLE_SERVICES = [
    {
        "name": "GitHub Pages",
        "cname": [".github.io"],
        "fingerprints": [
            "there isn't a github pages site here",
            "for root urls (like http://example.com/) you must provide an index.html file",
        ],
        "nxdomain": False,
    },
    {
        "name": "Heroku",
        "cname": [".herokuapp.com", ".herokussl.com", ".herokudns.com"],
        "fingerprints": [
            "no such app",
            "there is no app configured at that hostname",
            "herokucdn.com/error-pages/no-such-app",
        ],
        "nxdomain": False,
    },
    {
        "name": "AWS S3",
        "cname": [".s3.amazonaws.com", ".s3-website", ".s3."],
        "fingerprints": [
            "nosuchbucket",
            "the specified bucket does not exist",
        ],
        "nxdomain": False,
    },
    {
        "name": "Shopify",
        "cname": [".myshopify.com"],
        "fingerprints": [
            "sorry, this shop is currently unavailable",
            "only one step left",
        ],
        "nxdomain": False,
    },
    {
        "name": "Fastly",
        "cname": [".fastly.net", ".fastlylb.net"],
        "fingerprints": [
            "fastly error: unknown domain",
        ],
        "nxdomain": False,
    },
    {
        "name": "Pantheon",
        "cname": [".pantheonsite.io", ".pantheon.io"],
        "fingerprints": [
            "404 error unknown site",
            "the gods are wise",
        ],
        "nxdomain": False,
    },
    {
        "name": "Tumblr",
        "cname": [".tumblr.com"],
        "fingerprints": [
            "there's nothing here",
            "whatever you were looking for doesn't currently exist",
        ],
        "nxdomain": False,
    },
    {
        "name": "WordPress.com",
        "cname": [".wordpress.com"],
        "fingerprints": [
            "do you want to register",
        ],
        "nxdomain": False,
    },
    {
        "name": "Ghost",
        "cname": [".ghost.io"],
        "fingerprints": [
            "the thing you were looking for is no longer here",
        ],
        "nxdomain": False,
    },
    {
        "name": "Surge.sh",
        "cname": [".surge.sh"],
        "fingerprints": [
            "project not found",
        ],
        "nxdomain": False,
    },
    {
        "name": "Zendesk",
        "cname": [".zendesk.com"],
        "fingerprints": [
            "help center closed",
            "this help center no longer exists",
        ],
        "nxdomain": False,
    },
    {
        "name": "Readme.io",
        "cname": [".readme.io"],
        "fingerprints": [
            "project doesnt exist",
        ],
        "nxdomain": False,
    },
    {
        "name": "Bitbucket",
        "cname": [".bitbucket.io"],
        "fingerprints": [
            "repository not found",
        ],
        "nxdomain": False,
    },
    {
        "name": "Azure",
        "cname": [".azurewebsites.net", ".cloudapp.net", ".cloudapp.azure.com",
                  ".trafficmanager.net", ".blob.core.windows.net",
                  ".azure-api.net", ".azurefd.net", ".azureedge.net"],
        "fingerprints": [
            "error 404 - web app not found",
            "web app - unavailable",
            "the resource you are looking for has been removed",
        ],
        "nxdomain": True,  # NXDOMAIN su CNAME Azure = takeover possibile
    },
    {
        "name": "Fly.io",
        "cname": [".fly.dev"],
        "fingerprints": [
            "404 not found",
        ],
        "nxdomain": False,
    },
    {
        "name": "Unbounce",
        "cname": [".unbouncepages.com"],
        "fingerprints": [
            "the requested url was not found",
        ],
        "nxdomain": False,
    },
    {
        "name": "Tilda",
        "cname": [".tilda.ws"],
        "fingerprints": [
            "please renew your subscription",
        ],
        "nxdomain": False,
    },
    {
        "name": "Cargo Collective",
        "cname": [".cargocollective.com"],
        "fingerprints": [
            "404 not found",
        ],
        "nxdomain": False,
    },
    {
        "name": "Intercom",
        "cname": [".custom.intercom.help"],
        "fingerprints": [
            "this page is reserved for",
            "uh oh. that page doesn",
        ],
        "nxdomain": False,
    },
    {
        "name": "HelpScout",
        "cname": [".helpscoutdocs.com"],
        "fingerprints": [
            "no settings were found",
        ],
        "nxdomain": False,
    },
    {
        "name": "Ngrok",
        "cname": [".ngrok.io", ".ngrok.app"],
        "fingerprints": [
            "tunnel not found",
            "ngrok.com/docs",
        ],
        "nxdomain": False,
    },
    {
        "name": "Netlify",
        "cname": [".netlify.app", ".netlify.com"],
        "fingerprints": [
            "not found - request id",
        ],
        "nxdomain": True,
    },
    {
        "name": "Vercel",
        "cname": [".vercel.app", ".now.sh"],
        "fingerprints": [
            "the deployment could not be found",
        ],
        "nxdomain": False,
    },
]


class SubdomainTakeoverModule:
    """Cerca sottodomini vulnerabili a takeover (CNAME dangling)."""

    name = "subdomain_takeover"

    def __init__(self, http_session=None):
        if http_session:
            self.session = http_session
        else:
            from bugbounty_scanner.http_session import HttpSession
            self.session = HttpSession()

    def _enumerate_subdomains(self, domain):
        """Enumera sottodomini da fonti OSINT multiple.

        Fallback quando subfinder non è installato. Usa:
        1. crt.sh (Certificate Transparency)
        2. HackerTarget
        3. AlienVault OTX
        """
        subdomains = set()

        # 1. crt.sh (Certificate Transparency logs)
        try:
            logger.info("  [Takeover] Cerco sottodomini su crt.sh...")
            resp = requests.get(
                f"https://crt.sh/?q=%.{domain}&output=json",
                headers={"User-Agent": DEFAULT_USER_AGENT},
                timeout=20,
            )
            if resp.status_code == 200:
                for entry in resp.json():
                    name = entry.get("name_value", "")
                    for line in name.splitlines():
                        line = line.strip().lower()
                        if line and "*" not in line and line.endswith(domain):
                            subdomains.add(line)
                logger.info(f"  [Takeover] crt.sh: {len(subdomains)} sottodomini")
        except Exception as e:
            logger.debug(f"  [Takeover] crt.sh fallito: {e}")

        # 2. HackerTarget (free, no API key)
        try:
            logger.info("  [Takeover] Cerco sottodomini su HackerTarget...")
            resp = requests.get(
                f"https://api.hackertarget.com/hostsearch/?q={domain}",
                headers={"User-Agent": DEFAULT_USER_AGENT},
                timeout=20,
            )
            if resp.status_code == 200 and "error" not in resp.text.lower():
                for line in resp.text.splitlines():
                    parts = line.strip().split(",")
                    if parts and parts[0].endswith(domain):
                        subdomains.add(parts[0].lower())
                logger.info(f"  [Takeover] HackerTarget: totale {len(subdomains)} sottodomini")
        except Exception as e:
            logger.debug(f"  [Takeover] HackerTarget fallito: {e}")

        # 3. AlienVault OTX (free, no API key)
        try:
            logger.info("  [Takeover] Cerco sottodomini su AlienVault OTX...")
            resp = requests.get(
                f"https://otx.alienvault.com/api/v1/indicators/domain/{domain}/passive_dns",
                headers={"User-Agent": DEFAULT_USER_AGENT},
                timeout=20,
            )
            if resp.status_code == 200:
                data = resp.json()
                for record in data.get("passive_dns", []):
                    hostname = record.get("hostname", "").lower()
                    if hostname and hostname.endswith(domain):
                        subdomains.add(hostname)
                logger.info(f"  [Takeover] AlienVault: totale {len(subdomains)} sottodomini")
        except Exception as e:
            logger.debug(f"  [Takeover] AlienVault fallito: {e}")

        return sorted(subdomains)

    def run(self, target, scan_result):
        findings = []

        # Prendi sottodomini da subfinder, altrimenti usa crt.sh
        subdomains = getattr(scan_result, "subdomains", [])
        if not subdomains:
            # Estrai dominio dal target (può essere URL o stringa)
            if hasattr(target, "replace"):
                from urllib.parse import urlparse
                parsed = urlparse(target if "://" in target else f"https://{target}")
                domain = parsed.netloc or target
            else:
                domain = target
            domain = domain.split(":")[0]  # rimuovi porta

            logger.info(f"  [Takeover] Subfinder non ha trovato sottodomini, uso fonti OSINT per {domain}...")
            subdomains = self._enumerate_subdomains(domain)
            if subdomains:
                scan_result.subdomains = subdomains
                logger.info(f"  [Takeover] crt.sh ha trovato {len(subdomains)} sottodomini")
            else:
                logger.info("  [Takeover] Nessun sottodominio trovato nemmeno da crt.sh")
                return findings

        logger.info(f"  [Takeover] Test takeover su {len(subdomains)} sottodomini...")

        tested = 0
        for subdomain in subdomains:
            subdomain = subdomain.strip().lower()
            if not subdomain:
                continue

            tested += 1
            result = self._check_takeover(subdomain)
            if result:
                service_name, evidence = result
                findings.append(Finding(
                    title=f"Subdomain Takeover ({service_name}) - {subdomain}",
                    severity=SEVERITY_HIGH,
                    url=f"https://{subdomain}",
                    description=(
                        f"Il sottodominio {subdomain} ha un CNAME che punta a {service_name}, "
                        f"ma il servizio non è configurato. Un attaccante può reclamare "
                        f"questo servizio e servire contenuto malevolo su {subdomain}."
                    ),
                    evidence=evidence,
                    remediation=(
                        f"1. Rimuovi il record DNS CNAME per {subdomain} se il servizio "
                        f"non è più in uso. "
                        f"2. Oppure riconfigura il servizio {service_name} per reclamare "
                        f"il sottodominio. "
                        f"3. Verifica tutti i record DNS per altri CNAME orfani."
                    ),
                    module=self.name,
                    cwe="CWE-284",
                ))

        logger.info(f"  [Takeover] Testati {tested} sottodomini, {len(findings)} takeover trovati")
        return findings

    def _check_takeover(self, subdomain):
        """Controlla se un sottodominio è vulnerabile a takeover.

        Returns:
            Tuple (service_name, evidence) se vulnerabile, None altrimenti.
        """
        # Step 1: Risolvi CNAME
        cname = self._get_cname(subdomain)
        if not cname:
            return None

        cname_lower = cname.lower()
        logger.debug(f"  [Takeover] {subdomain} → CNAME: {cname}")

        # Step 2: Cerca se il CNAME matcha un servizio vulnerabile
        for service in VULNERABLE_SERVICES:
            cname_match = any(pat in cname_lower for pat in service["cname"])
            if not cname_match:
                continue

            # Step 3: Controlla se il CNAME è NXDOMAIN (non risolve)
            is_nxdomain = not self._resolves(cname)
            if is_nxdomain and service.get("nxdomain"):
                evidence = (
                    f"CNAME: {subdomain} → {cname}\n"
                    f"Servizio: {service['name']}\n"
                    f"Il CNAME target ({cname}) non risolve (NXDOMAIN).\n"
                    f"Il sottodominio può essere reclamato su {service['name']}."
                )
                logger.info(f"  [Takeover] CONFERMATO (NXDOMAIN): {subdomain} → {cname} ({service['name']})")
                return service["name"], evidence

            # Step 4: Verifica fingerprint HTTP
            fingerprint_match = self._check_http_fingerprint(subdomain, service)
            if fingerprint_match:
                evidence = (
                    f"CNAME: {subdomain} → {cname}\n"
                    f"Servizio: {service['name']}\n"
                    f"Fingerprint trovata: \"{fingerprint_match}\"\n"
                    f"Il sottodominio può essere reclamato su {service['name']}.\n"
                    f"\nVerifica manuale:\n"
                    f"  dig CNAME {subdomain}\n"
                    f"  curl -sI https://{subdomain}"
                )
                logger.info(f"  [Takeover] CONFERMATO (fingerprint): {subdomain} → {cname} ({service['name']})")
                return service["name"], evidence

        return None

    def _get_cname(self, subdomain):
        """Risolvi il record CNAME per un sottodominio. Ritorna il target CNAME o None."""
        # Prova con dig (più affidabile)
        try:
            result = subprocess.run(
                ["dig", "+short", "CNAME", subdomain],
                capture_output=True, text=True, timeout=10,
            )
            output = result.stdout.strip()
            if output and "." in output:
                # dig ritorna "target.example.com." con punto finale
                return output.rstrip(".")
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

        # Fallback: host command
        try:
            result = subprocess.run(
                ["host", "-t", "CNAME", subdomain],
                capture_output=True, text=True, timeout=10,
            )
            # Output: "subdomain.example.com is an alias for target.example.com."
            match = re.search(r'is an alias for (.+?)\.?$', result.stdout, re.MULTILINE)
            if match:
                return match.group(1).rstrip(".")
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

        return None

    def _resolves(self, hostname):
        """Controlla se un hostname risolve via DNS."""
        hostname = hostname.rstrip(".")
        try:
            socket.getaddrinfo(hostname, None, socket.AF_INET, socket.SOCK_STREAM)
            return True
        except (socket.gaierror, OSError):
            return False

    def _check_http_fingerprint(self, subdomain, service):
        """Fa una richiesta HTTP al sottodominio e cerca le fingerprint del servizio.

        Returns:
            La fingerprint trovata, o None.
        """
        for scheme in ["https", "http"]:
            try:
                resp = requests.get(
                    f"{scheme}://{subdomain}",
                    headers={"User-Agent": DEFAULT_USER_AGENT},
                    timeout=10,
                    allow_redirects=True,
                    verify=False,
                )
                body_lower = resp.text.lower()

                for fingerprint in service["fingerprints"]:
                    if fingerprint in body_lower:
                        return fingerprint

            except requests.RequestException:
                continue

        return None
