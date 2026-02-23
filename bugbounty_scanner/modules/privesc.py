"""Privilege Escalation / IDOR detection module.

Covers:
  - Insecure Direct Object Reference (IDOR) on user/admin resources
  - Horizontal and vertical privilege escalation via parameter tampering
  - Mass assignment / role escalation via API
  - Auth bypass on admin endpoints
  - JWT algorithm confusion (none/HS256)
"""

import logging
import re
import json
import base64
import hashlib
from urllib.parse import urlparse, urljoin, parse_qs, urlencode, urlunparse

import requests
from bs4 import BeautifulSoup

from bugbounty_scanner.config import (
    DEFAULT_TIMEOUT,
    SEVERITY_CRITICAL,
    SEVERITY_HIGH,
    SEVERITY_MEDIUM,
    SEVERITY_LOW,
)
from bugbounty_scanner.scanner import Finding

logger = logging.getLogger("bugbounty_scanner")


# Common admin/privileged paths to probe
ADMIN_PATHS = [
    "/admin", "/admin/", "/administrator", "/admin/dashboard",
    "/admin/users", "/admin/panel", "/wp-admin", "/manager",
    "/backend", "/cms", "/control", "/controlpanel", "/cpanel",
    "/superadmin", "/root", "/system", "/manage", "/management",
    "/api/admin", "/api/v1/admin", "/api/users", "/api/v1/users",
    # Royal CMS specific
    "/royal-admin", "/royal/admin", "/admin/royal", "/cms/admin",
    "/index.php?p=admin", "/index.php?page=admin",
]

# IDOR parameter names (numeric IDs)
IDOR_PARAMS = [
    "id", "user_id", "userid", "uid", "account", "account_id",
    "order", "order_id", "invoice", "invoice_id", "doc", "document_id",
    "file_id", "resource_id", "pid", "profile", "profile_id",
    "customer_id", "client_id", "member_id", "record_id",
]

# Role/privilege parameters to tamper
ROLE_PARAMS = [
    "role", "group", "admin", "isAdmin", "is_admin", "privilege",
    "level", "type", "user_type", "account_type", "permission",
    "access", "scope", "rank",
]

ROLE_VALUES = ["admin", "administrator", "superadmin", "root", "1", "true", "True", "ADMIN", "manager"]


class PrivEscModule:
    """Detects privilege escalation and IDOR vulnerabilities."""

    name = "privesc"

    def __init__(self, http_session=None):
        if http_session:
            self.session = http_session
        else:
            from bugbounty_scanner.http_session import HttpSession
            self.session = HttpSession()

    def run(self, target, scan_result):
        findings = []
        parsed = urlparse(target)
        base = f"{parsed.scheme}://{parsed.netloc}"

        # 1. Admin endpoint discovery
        findings.extend(self._probe_admin_paths(base, target))

        # 2. IDOR on URL parameters
        findings.extend(self._test_idor(target, scan_result))

        # 3. Role parameter tampering
        findings.extend(self._test_role_tampering(target, scan_result))

        # 4. JWT manipulation (if cookies/headers contain JWT)
        findings.extend(self._test_jwt(target))

        # 5. Mass assignment via API endpoints
        findings.extend(self._test_mass_assignment(target, scan_result))

        return findings

    # ------------------------------------------------------------------
    # Admin path probing
    # ------------------------------------------------------------------

    def _probe_admin_paths(self, base, target):
        """Check if admin paths are accessible without authentication."""
        findings = []

        # Get baseline response for a non-existent page
        baseline_status = 404
        try:
            chk = self.session.get(f"{base}/this-page-definitely-does-not-exist-xyz123", timeout=DEFAULT_TIMEOUT)
            baseline_status = chk.status_code
        except requests.RequestException:
            pass

        for path in ADMIN_PATHS:
            url = base + path
            try:
                resp = self.session.get(url, timeout=DEFAULT_TIMEOUT, allow_redirects=False)

                # 200 = accessible without redirect to login
                if resp.status_code == 200 and len(resp.text) > 200:
                    title = self._extract_title(resp.text)
                    # Check it's not just a generic 404/error page
                    if not re.search(r"404|not found|error|page not found", title, re.IGNORECASE):
                        findings.append(Finding(
                            title=f"Admin Panel accessibile senza autenticazione: {path}",
                            severity=SEVERITY_CRITICAL,
                            url=url,
                            description=(
                                f"Il pannello di amministrazione '{path}' è accessibile "
                                f"senza richiedere autenticazione (HTTP {resp.status_code})."
                            ),
                            evidence=f"URL: {url}\nHTTP Status: {resp.status_code}\nTitle: {title}",
                            remediation=(
                                "Proteggere tutti gli endpoint admin con autenticazione e autorizzazione. "
                                "Implementare controllo degli accessi basato su ruoli (RBAC). "
                                "Restituire 401/403 per accessi non autorizzati, non 200."
                            ),
                            module=self.name,
                            cwe="CWE-284",
                        ))

                # 403 = path exists but blocked (lower severity, auth bypass possible)
                elif resp.status_code == 403:
                    findings.append(Finding(
                        title=f"Admin Panel rilevato (403 Forbidden): {path}",
                        severity=SEVERITY_MEDIUM,
                        url=url,
                        description=(
                            f"L'endpoint '{path}' esiste e risponde 403. "
                            f"Potrebbe essere bypassabile con tecniche di path confusion o header manipulation."
                        ),
                        evidence=f"URL: {url}\nHTTP Status: 403",
                        remediation="Verificare che il blocco 403 non sia bypassabile tramite variazioni del path o header speciali.",
                        module=self.name,
                        cwe="CWE-284",
                    ))

            except requests.RequestException:
                continue

        return findings

    # ------------------------------------------------------------------
    # IDOR
    # ------------------------------------------------------------------

    def _test_idor(self, target, scan_result):
        """Test numeric ID parameters for IDOR."""
        findings = []
        parsed = urlparse(target)
        params = parse_qs(parsed.query, keep_blank_values=True)

        idor_candidates = {k: v for k, v in params.items() if k.lower() in IDOR_PARAMS}

        # Also scan discovered params
        for param_info in getattr(scan_result, "discovered_params", []):
            pname = param_info.split(" (")[0].strip()
            if pname.lower() in IDOR_PARAMS and pname not in idor_candidates:
                idor_candidates[pname] = ["1"]

        for param_name, values in idor_candidates.items():
            original_value = values[0] if isinstance(values, list) else values
            try:
                original_id = int(original_value)
            except (ValueError, TypeError):
                continue

            # Try adjacent IDs
            test_ids = [original_id - 1, original_id + 1, original_id + 10]
            test_ids = [i for i in test_ids if i > 0]

            try:
                base_params = {k: v[0] if isinstance(v, list) else v for k, v in params.items()}
                original_url = urlunparse((
                    parsed.scheme, parsed.netloc, parsed.path, parsed.params,
                    urlencode(base_params), parsed.fragment,
                ))
                original_resp = self.session.get(original_url, timeout=DEFAULT_TIMEOUT)
                original_len = len(original_resp.text)
                original_body = original_resp.text
            except requests.RequestException:
                continue

            for test_id in test_ids:
                test_params = dict(base_params)
                test_params[param_name] = str(test_id)
                test_url = urlunparse((
                    parsed.scheme, parsed.netloc, parsed.path, parsed.params,
                    urlencode(test_params), parsed.fragment,
                ))
                try:
                    resp = self.session.get(test_url, timeout=DEFAULT_TIMEOUT)

                    # Successful IDOR: 200 response with different non-error content
                    if (resp.status_code == 200
                            and len(resp.text) > 100
                            and resp.text != original_body
                            and not re.search(r"404|not found|error|forbidden|unauthorized", resp.text[:500], re.IGNORECASE)):

                        findings.append(Finding(
                            title=f"IDOR (Insecure Direct Object Reference) in '{param_name}'",
                            severity=SEVERITY_HIGH,
                            url=test_url,
                            description=(
                                f"Il parametro '{param_name}' è vulnerabile a IDOR. "
                                f"Cambiando il valore da {original_id} a {test_id} si accede "
                                f"a risorse di altri utenti senza autorizzazione."
                            ),
                            evidence=(
                                f"URL originale (id={original_id}): {original_url}\n"
                                f"URL IDOR (id={test_id}): {test_url}\n"
                                f"Risposta: HTTP 200, {len(resp.text)} byte"
                            ),
                            remediation=(
                                "Implementare controllo dell'autorizzazione server-side per ogni accesso a oggetti. "
                                "Verificare che l'utente autenticato abbia i permessi per l'oggetto richiesto. "
                                "Usare identificatori non prevedibili (UUID) invece di ID sequenziali."
                            ),
                            module=self.name,
                            cwe="CWE-639",
                        ))
                        break

                except requests.RequestException:
                    continue

        return findings

    # ------------------------------------------------------------------
    # Role parameter tampering
    # ------------------------------------------------------------------

    def _test_role_tampering(self, target, scan_result):
        """Test if role/privilege parameters can be escalated."""
        findings = []
        parsed = urlparse(target)
        params = parse_qs(parsed.query, keep_blank_values=True)

        role_candidates = [k for k in params if k.lower() in ROLE_PARAMS]

        # Check forms too
        for form in getattr(scan_result, "discovered_forms", []):
            for field in form.get("fields", []):
                if field.lower() in ROLE_PARAMS and field not in role_candidates:
                    role_candidates.append(field)

        for param_name in role_candidates:
            original_value = params.get(param_name, ["user"])[0]

            for role_value in ROLE_VALUES:
                if role_value == original_value:
                    continue

                test_params = {k: v[0] if isinstance(v, list) else v for k, v in params.items()}
                test_params[param_name] = role_value
                test_url = urlunparse((
                    parsed.scheme, parsed.netloc, parsed.path, parsed.params,
                    urlencode(test_params), parsed.fragment,
                ))
                try:
                    resp = self.session.get(test_url, timeout=DEFAULT_TIMEOUT)
                    if resp.status_code == 200 and not re.search(
                        r"invalid|forbidden|unauthorized|error|not allowed",
                        resp.text[:1000], re.IGNORECASE
                    ):
                        # Check if we got admin-level content
                        if re.search(r"admin|dashboard|panel|manage|settings|config", resp.text, re.IGNORECASE):
                            findings.append(Finding(
                                title=f"Privilege Escalation via parametro '{param_name}'",
                                severity=SEVERITY_CRITICAL,
                                url=test_url,
                                description=(
                                    f"Il parametro '{param_name}' può essere manipolato per "
                                    f"scalare i privilegi. Impostando il valore a '{role_value}' "
                                    f"si ottiene accesso a funzionalità privilegiate."
                                ),
                                evidence=f"Param: {param_name}={role_value}\nURL: {test_url}\nHTTP {resp.status_code}",
                                remediation=(
                                    "Non fidarsi mai di parametri lato client per determinare i permessi. "
                                    "Il ruolo utente deve essere letto dalla sessione server-side. "
                                    "Implementare RBAC con verifica server-side a ogni richiesta."
                                ),
                                module=self.name,
                                cwe="CWE-269",
                            ))
                            break
                except requests.RequestException:
                    continue

        return findings

    # ------------------------------------------------------------------
    # JWT manipulation
    # ------------------------------------------------------------------

    def _test_jwt(self, target):
        """Check for JWT tokens and test algorithm confusion (none/HS256)."""
        findings = []
        try:
            resp = self.session.get(target, timeout=DEFAULT_TIMEOUT)
        except requests.RequestException:
            return findings

        # Extract JWTs from cookies and response headers
        jwt_tokens = []
        for cookie_name, cookie_value in self.session.session.cookies.items():
            if self._is_jwt(cookie_value):
                jwt_tokens.append((f"Cookie: {cookie_name}", cookie_value))

        auth_header = resp.headers.get("Authorization", "")
        if auth_header.startswith("Bearer ") and self._is_jwt(auth_header[7:]):
            jwt_tokens.append(("Header: Authorization", auth_header[7:]))

        # Check response body for JWT
        jwt_re = re.findall(r'eyJ[A-Za-z0-9\-_]+\.[A-Za-z0-9\-_]+\.[A-Za-z0-9\-_]*', resp.text)
        for tok in jwt_re:
            jwt_tokens.append(("Response body", tok))

        for location, token in jwt_tokens:
            result = self._analyze_jwt(token)
            if result:
                findings.append(Finding(
                    title=f"JWT vulnerabile - {result['issue']}",
                    severity=SEVERITY_HIGH,
                    url=target,
                    description=result["description"],
                    evidence=f"Posizione: {location}\nToken: {token[:80]}...\nAnalisi: {result['detail']}",
                    remediation=result["remediation"],
                    module=self.name,
                    cwe="CWE-327",
                ))

        return findings

    def _is_jwt(self, value):
        """Check if a string looks like a JWT."""
        return bool(re.match(r'^eyJ[A-Za-z0-9\-_]+\.[A-Za-z0-9\-_]+\.[A-Za-z0-9\-_]*$', value or ""))

    def _analyze_jwt(self, token):
        """Analyze JWT for common vulnerabilities."""
        try:
            parts = token.split(".")
            if len(parts) != 3:
                return None

            header_data = json.loads(base64.urlsafe_b64decode(parts[0] + "=="))
            alg = header_data.get("alg", "")

            if alg.lower() == "none":
                return {
                    "issue": "Algoritmo 'none' accettato",
                    "description": "Il JWT usa l'algoritmo 'none', che non richiede firma. Chiunque può creare token validi.",
                    "detail": f"Header: {header_data}",
                    "remediation": "Rifiutare esplicitamente l'algoritmo 'none'. Usare RS256 o HS256 con chiave sicura.",
                }
            elif alg.lower() == "hs256":
                return {
                    "issue": "Algoritmo HS256 (verifica chiave debole consigliata)",
                    "description": "Il JWT usa HS256. Se la chiave segreta è debole, può essere bruteforzata.",
                    "detail": f"Header: {header_data}",
                    "remediation": "Usare una chiave segreta lunga (>256 bit) e casuale. Considerare RS256 per scalabilità.",
                }
        except Exception:
            pass
        return None

    # ------------------------------------------------------------------
    # Mass assignment
    # ------------------------------------------------------------------

    def _test_mass_assignment(self, target, scan_result):
        """Test API endpoints for mass assignment / parameter pollution."""
        findings = []
        parsed = urlparse(target)
        base = f"{parsed.scheme}://{parsed.netloc}"

        # Common API patterns
        api_paths = [
            "/api/user/update", "/api/v1/user/update", "/api/profile",
            "/api/v1/profile", "/user/update", "/profile/update",
            "/api/users/me", "/api/account",
        ]

        for path in api_paths:
            url = base + path
            for role_field in ROLE_PARAMS[:5]:
                try:
                    payload = {role_field: "admin"}
                    resp = self.session.post(
                        url,
                        json=payload,
                        timeout=DEFAULT_TIMEOUT,
                        allow_redirects=True,
                    )
                    if resp.status_code == 200:
                        try:
                            data = resp.json()
                            # If the response contains our injected role value
                            resp_str = json.dumps(data).lower()
                            if "admin" in resp_str and role_field in resp_str:
                                findings.append(Finding(
                                    title=f"Mass Assignment - Escalation via '{role_field}' su {path}",
                                    severity=SEVERITY_HIGH,
                                    url=url,
                                    description=(
                                        f"L'endpoint '{path}' accetta il campo '{role_field}' "
                                        f"e lo riflette nella risposta, indicando possibile mass assignment."
                                    ),
                                    evidence=f"POST {url}\nBody: {json.dumps(payload)}\nRisposta: {str(data)[:300]}",
                                    remediation=(
                                        "Usare DTO (Data Transfer Objects) o whitelist esplicite dei campi accettati. "
                                        "Non esporre mai campi privilegiati (role, is_admin) nelle API pubbliche."
                                    ),
                                    module=self.name,
                                    cwe="CWE-915",
                                ))
                                break
                        except ValueError:
                            pass
                except requests.RequestException:
                    continue

        return findings

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _extract_title(self, html):
        try:
            soup = BeautifulSoup(html, "html.parser")
            title = soup.find("title")
            return title.get_text(strip=True) if title else ""
        except Exception:
            return ""
