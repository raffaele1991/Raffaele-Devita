"""
Scope Checker - verifica che ogni richiesta sia in scope.

Si aggancia alla sessione HTTP e blocca automaticamente
le richieste verso domini fuori scope.
"""

import logging
from urllib.parse import urlparse

from bugbounty_scanner.program_parser import ProgramInfo

logger = logging.getLogger("bugbounty_scanner")


class ScopeChecker:
    """
    Verifica che URL e domini siano in scope prima di ogni richiesta.

    Uso:
        checker = ScopeChecker(program_info)
        checker.check("https://api.target.com/users")  # True
        checker.check("https://out-of-scope.com/")      # False, lancia ScopeError
    """

    def __init__(self, program_info: ProgramInfo):
        self.program = program_info
        self.blocked_count = 0
        self.allowed_count = 0
        self._blocked_domains = set()

    def is_in_scope(self, url):
        """Verifica se un URL è in scope. Ritorna True/False."""
        if not self.program.in_scope_domains and not self.program.out_of_scope_domains:
            return True  # Nessuno scope definito = tutto permesso

        return self.program.is_in_scope(url)

    def check(self, url):
        """
        Verifica scope e logga. Ritorna True se permesso, False se bloccato.
        """
        if self.is_in_scope(url):
            self.allowed_count += 1
            return True
        else:
            domain = urlparse(url).netloc if "://" in url else url
            self.blocked_count += 1
            if domain not in self._blocked_domains:
                self._blocked_domains.add(domain)
                logger.warning(f"  [SCOPE] BLOCCATO: {domain} (fuori scope)")
            return False

    def filter_urls(self, urls):
        """Filtra una lista di URL e ritorna solo quelli in scope."""
        return [u for u in urls if self.check(u)]

    def filter_domains(self, domains):
        """Filtra una lista di domini e ritorna solo quelli in scope."""
        return [d for d in domains if self.check(d)]

    def summary(self):
        """Riepilogo delle verifiche di scope."""
        total = self.allowed_count + self.blocked_count
        return (
            f"Scope check: {self.allowed_count} permessi, "
            f"{self.blocked_count} bloccati su {total} totali. "
            f"Domini bloccati: {', '.join(self._blocked_domains) if self._blocked_domains else 'nessuno'}"
        )
