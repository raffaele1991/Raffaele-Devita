"""Rate limiter e gestione sessioni HTTP con header custom."""

import time
import threading
import logging

import requests

from bugbounty_scanner.config import DEFAULT_USER_AGENT, DEFAULT_TIMEOUT

logger = logging.getLogger("bugbounty_scanner")


class RateLimiter:
    """
    Rate limiter thread-safe.
    Garantisce un massimo di N richieste al secondo.
    """

    def __init__(self, max_per_second=5):
        self.max_per_second = max_per_second
        self.interval = 1.0 / max_per_second if max_per_second > 0 else 0
        self._lock = threading.Lock()
        self._last_request = 0.0

    def wait(self):
        """Aspetta il tempo necessario prima della prossima richiesta."""
        if self.interval <= 0:
            return

        with self._lock:
            now = time.time()
            elapsed = now - self._last_request
            if elapsed < self.interval:
                sleep_time = self.interval - elapsed
                time.sleep(sleep_time)
            self._last_request = time.time()


class HttpSession:
    """
    Sessione HTTP configurata con header custom, rate limiting e identificazione.

    Uso:
        session = HttpSession(
            headers={"X-Bug-Bounty": "kobraraf91"},
            email="kobraraf91@intigriti.me",
            rate_limit=5,
        )
        resp = session.get("https://target.com/page")
    """

    def __init__(self, headers=None, email=None, rate_limit=5, user_agent=None, timeout=None):
        self.session = requests.Session()
        self.rate_limiter = RateLimiter(max_per_second=rate_limit)
        self.timeout = timeout or DEFAULT_TIMEOUT

        # User-Agent
        self.session.headers["User-Agent"] = user_agent or DEFAULT_USER_AGENT

        # Email identificativa - aggiunta in header standard
        if email:
            self.session.headers["X-Bug-Bounty-Contact"] = email
            self.session.headers["From"] = email

        # Header custom (es: X-Bug-Bounty, Authorization, ecc.)
        if headers:
            for key, value in headers.items():
                self.session.headers[key] = value

        # Disabilita verifica SSL per test
        self.session.verify = False

    def get(self, url, **kwargs):
        """GET con rate limiting."""
        self.rate_limiter.wait()
        kwargs.setdefault("timeout", self.timeout)
        return self.session.get(url, **kwargs)

    def post(self, url, **kwargs):
        """POST con rate limiting."""
        self.rate_limiter.wait()
        kwargs.setdefault("timeout", self.timeout)
        return self.session.post(url, **kwargs)

    def head(self, url, **kwargs):
        """HEAD con rate limiting."""
        self.rate_limiter.wait()
        kwargs.setdefault("timeout", self.timeout)
        return self.session.head(url, **kwargs)

    def request(self, method, url, **kwargs):
        """Request generico con rate limiting."""
        self.rate_limiter.wait()
        kwargs.setdefault("timeout", self.timeout)
        return self.session.request(method, url, **kwargs)

    @property
    def headers(self):
        return self.session.headers

    @property
    def cookies(self):
        return self.session.cookies


def parse_header_string(header_str):
    """
    Parsa una stringa header nel formato 'Nome: Valore'.

    Supporta formati:
        "X-Bug-Bounty: kobraraf91"
        "X-Bug-Bounty:kobraraf91"
        "Authorization: Bearer token123"
    """
    if ":" not in header_str:
        raise ValueError(f"Header non valido (manca ':'): {header_str}")

    key, _, value = header_str.partition(":")
    return key.strip(), value.strip()


def parse_headers_list(headers_list):
    """Parsa una lista di stringhe header in un dizionario."""
    result = {}
    if not headers_list:
        return result

    for h in headers_list:
        key, value = parse_header_string(h)
        result[key] = value

    return result
