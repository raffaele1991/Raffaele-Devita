"""Scanner configuration and constants."""

import os

# HTTP settings
DEFAULT_TIMEOUT = 10
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
MAX_RETRIES = 2
DELAY_BETWEEN_REQUESTS = 0.5  # seconds

# Scanner settings
MAX_THREADS = 10
FOLLOW_REDIRECTS = True

# Severity levels
SEVERITY_CRITICAL = "CRITICAL"
SEVERITY_HIGH = "HIGH"
SEVERITY_MEDIUM = "MEDIUM"
SEVERITY_LOW = "LOW"
SEVERITY_INFO = "INFO"

# Common ports for scanning
COMMON_PORTS = [
    21, 22, 23, 25, 53, 80, 110, 111, 135, 139, 143, 443, 445, 993, 995,
    1723, 3306, 3389, 5432, 5900, 8000, 8080, 8443, 8888, 9090,
]

# XSS payloads
XSS_PAYLOADS = [
    '<script>alert(1)</script>',
    '"><script>alert(1)</script>',
    "'-alert(1)-'",
    '<img src=x onerror=alert(1)>',
    '"><img src=x onerror=alert(1)>',
    "javascript:alert(1)",
    '<svg/onload=alert(1)>',
    '{{7*7}}',
    '${7*7}',
    '<iframe src="javascript:alert(1)">',
]

# SQL injection payloads
SQLI_PAYLOADS = [
    "' OR '1'='1",
    "' OR '1'='1' --",
    "' OR '1'='1' /*",
    '" OR "1"="1',
    "1' ORDER BY 1--",
    "1' ORDER BY 100--",
    "1 UNION SELECT NULL--",
    "1' UNION SELECT NULL--",
    "' AND 1=1--",
    "' AND 1=2--",
    "1; WAITFOR DELAY '0:0:5'--",
    "1' AND SLEEP(5)--",
]

# SQL error patterns
SQL_ERROR_PATTERNS = [
    "you have an error in your sql syntax",
    "warning: mysql",
    "unclosed quotation mark",
    "quoted string not properly terminated",
    "microsoft ole db provider for sql server",
    "postgresql.*error",
    "ora-[0-9]{5}",
    "sqlite3.operationalerror",
    "pg_query",
    "mysql_fetch",
    "syntax error.*sql",
    "unterminated string literal",
    "invalid input syntax for",
    "sqlstate",
]

# SSRF payloads
SSRF_PAYLOADS = [
    "http://127.0.0.1",
    "http://localhost",
    "http://0.0.0.0",
    "http://[::1]",
    "http://127.0.0.1:80",
    "http://127.0.0.1:443",
    "http://127.0.0.1:22",
    "http://169.254.169.254/latest/meta-data/",
    "http://metadata.google.internal/",
    "http://100.100.100.200/latest/meta-data/",
]

# Open redirect payloads
OPEN_REDIRECT_PAYLOADS = [
    "//evil.com",
    "https://evil.com",
    "/\\evil.com",
    "//evil.com/%2f..",
    "///evil.com",
    "////evil.com",
    "https:evil.com",
    r"\/\/evil.com",
    "/redirect?url=https://evil.com",
]

# Header injection payloads
HEADER_INJECTION_PAYLOADS = [
    "valuE\r\nInjected-Header: true",
    "value%0d%0aInjected-Header:%20true",
    "value\nInjected-Header: true",
]

# Sensitive file paths to check
SENSITIVE_PATHS = [
    "/.env",
    "/.git/config",
    "/.git/HEAD",
    "/.svn/entries",
    "/.DS_Store",
    "/wp-config.php",
    "/config.php",
    "/configuration.php",
    "/.htaccess",
    "/.htpasswd",
    "/web.config",
    "/crossdomain.xml",
    "/phpinfo.php",
    "/server-status",
    "/server-info",
    "/robots.txt",
    "/sitemap.xml",
    "/.well-known/security.txt",
    "/api/swagger.json",
    "/api/v1/swagger.json",
    "/swagger-ui.html",
    "/api-docs",
    "/graphql",
    "/graphiql",
    "/.dockerenv",
    "/Dockerfile",
    "/docker-compose.yml",
    "/backup.sql",
    "/dump.sql",
    "/database.sql",
    "/admin",
    "/admin/login",
    "/administrator",
    "/wp-admin",
    "/wp-login.php",
    "/actuator",
    "/actuator/health",
    "/actuator/env",
    "/trace",
    "/debug",
    "/console",
    "/.aws/credentials",
    "/etc/passwd",
]

# Security headers to check
SECURITY_HEADERS = [
    "Strict-Transport-Security",
    "Content-Security-Policy",
    "X-Content-Type-Options",
    "X-Frame-Options",
    "X-XSS-Protection",
    "Referrer-Policy",
    "Permissions-Policy",
    "Cross-Origin-Opener-Policy",
    "Cross-Origin-Resource-Policy",
    "Cross-Origin-Embedder-Policy",
]

# Interesting response headers that leak info
INFO_LEAK_HEADERS = [
    "Server",
    "X-Powered-By",
    "X-AspNet-Version",
    "X-AspNetMvc-Version",
    "X-Runtime",
    "X-Version",
    "X-Generator",
]

# Subdomain wordlist (compact)
SUBDOMAIN_WORDLIST = [
    "www", "mail", "ftp", "admin", "blog", "dev", "staging", "test",
    "api", "app", "cdn", "cloud", "cms", "cpanel", "dashboard", "demo",
    "docs", "email", "gateway", "git", "gitlab", "grafana", "graphql",
    "help", "internal", "jenkins", "jira", "kibana", "login", "m",
    "manage", "monitor", "mysql", "new", "ns1", "ns2", "old", "panel",
    "portal", "prod", "proxy", "rdp", "redis", "remote", "repo",
    "search", "secure", "shop", "sso", "stage", "static", "status",
    "store", "support", "vpn", "webmail", "wiki", "www2",
]
