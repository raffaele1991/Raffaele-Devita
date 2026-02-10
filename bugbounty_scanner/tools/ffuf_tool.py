"""Wrapper per ffuf - fuzzer web veloce per directory e file."""

import logging
import os

from bugbounty_scanner.tools.base import BaseTool
from bugbounty_scanner.scanner import Finding
from bugbounty_scanner.config import SEVERITY_LOW, SEVERITY_MEDIUM, SEVERITY_INFO

logger = logging.getLogger("bugbounty_scanner")

# Wordlist compatta per directory/file comuni
DEFAULT_WORDLIST = """admin
administrator
api
api/v1
api/v2
app
assets
auth
backup
backups
beta
blog
cdn
cgi-bin
config
console
cp
dashboard
db
debug
deploy
dev
docs
download
dump
editor
email
error
export
files
graphql
health
help
images
import
include
internal
jenkins
jira
js
kibana
login
logout
logs
manage
manager
metrics
monitor
new
old
panel
phpmyadmin
portal
private
prod
profile
proxy
public
readme
register
remote
repo
reset
robots.txt
rss
search
secret
secure
security
server-info
server-status
settings
setup
shell
shop
signin
signup
sitemap.xml
sso
staging
static
status
storage
support
swagger
system
test
testing
tmp
tools
trace
upload
uploads
user
users
vendor
version
web
webmail
wiki
wp-admin
wp-content
wp-includes
wp-login.php
xmlrpc.php
.env
.git
.git/config
.git/HEAD
.htaccess
.htpasswd
.svn
.well-known/security.txt
"""


class FfufTool(BaseTool):
    """
    ffuf - Fuzz Faster U Fool. Fuzzer web ultra-veloce.
    https://github.com/ffuf/ffuf
    """

    name = "ffuf"
    binary = "ffuf"
    install_url = "https://github.com/ffuf/ffuf"

    def __init__(self, wordlist=None, threads=40, rate_limit=0):
        super().__init__()
        self.wordlist = wordlist
        self.threads = threads
        self.rate_limit = rate_limit

    def run(self, target, scan_result):
        self.check_installed()
        findings = []

        # Usa wordlist custom o quella di default
        if self.wordlist and os.path.exists(self.wordlist):
            wordlist_path = self.wordlist
        else:
            wordlist_path = self.make_temp_file(DEFAULT_WORDLIST, suffix=".txt")

        logger.info(f"  [ffuf] Fuzzing directory su {target.base_url}")

        url = f"{target.base_url}/FUZZ"

        args = [
            "-u", url,
            "-w", wordlist_path,
            "-o", "/dev/stdout",
            "-of", "json",
            "-mc", "200,201,202,204,301,302,307,401,403,405",
            "-fc", "404",
            "-t", str(self.threads),
            "-s",  # silent
            "-timeout", "10",
        ]

        if self.rate_limit > 0:
            args.extend(["-rate", str(self.rate_limit)])

        output = self.run_command(args, timeout=300, parse_json=True)

        if not output:
            return findings

        # ffuf JSON ha una struttura con "results"
        results = output
        if isinstance(output, dict):
            results = output.get("results", [])

        if not isinstance(results, list):
            return findings

        interesting_paths = []

        for entry in results:
            if not isinstance(entry, dict):
                continue

            path = entry.get("input", {}).get("FUZZ", "") if isinstance(entry.get("input"), dict) else ""
            status = entry.get("status", 0)
            length = entry.get("length", 0)
            url_found = entry.get("url", f"{target.base_url}/{path}")

            if not path:
                continue

            interesting_paths.append(f"/{path} [{status}] ({length} bytes)")

            # Classifica per gravità
            severity = SEVERITY_INFO
            if path in (".env", ".git/config", ".git/HEAD", ".htpasswd", "backup", "dump"):
                severity = SEVERITY_MEDIUM
            elif status == 401 or status == 403:
                severity = SEVERITY_LOW
            elif status == 200 and path in (
                "admin", "dashboard", "console", "phpmyadmin", "jenkins",
                "debug", "server-status", "server-info", "graphql",
            ):
                severity = SEVERITY_MEDIUM

            findings.append(Finding(
                title=f"Path trovato: /{path}",
                severity=severity,
                url=url_found,
                description=f"ffuf ha trovato il path '/{path}' con status {status}.",
                evidence=f"Status: {status}, Dimensione: {length} bytes",
                module=self.name,
            ))

        if interesting_paths:
            logger.info(f"  [ffuf] Trovati {len(interesting_paths)} path")

        return findings
