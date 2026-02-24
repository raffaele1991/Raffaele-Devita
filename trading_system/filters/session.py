"""
Session Filter – Kill Zone
===========================
Il bot opera SOLO durante le kill zone istituzionali.
Orari in CET (Europe/Rome): London 08-11, NY 14-17.
"""

from datetime import datetime, time
import pytz
from trading_system import config


class SessionFilter:
    """
    Controlla se l'orario corrente è dentro una kill zone valida.
    """

    def __init__(self):
        self.tz = pytz.timezone("Europe/Rome")  # CET / CEST automatico

        def parse(t_str: str) -> time:
            h, m = t_str.split(":")
            return time(int(h), int(m))

        self.london_start = parse(config.SESSION_LONDON_START)
        self.london_end   = parse(config.SESSION_LONDON_END)
        self.ny_start     = parse(config.SESSION_NY_START)
        self.ny_end       = parse(config.SESSION_NY_END)

        self.eod_hour = config.PROP_CLOSE_EOD_HOUR

    def current_time_cet(self) -> time:
        now = datetime.now(self.tz)
        return now.time()

    def is_active(self) -> bool:
        """True se siamo in London Kill Zone o NY Kill Zone."""
        now = self.current_time_cet()

        # Fine giornata: no nuovi trade
        if now.hour >= self.eod_hour:
            return False

        in_london = self.london_start <= now <= self.london_end
        in_ny     = self.ny_start     <= now <= self.ny_end

        return in_london or in_ny

    def active_session(self) -> str:
        """Ritorna la sessione attiva o 'CLOSED'."""
        now = self.current_time_cet()
        if now.hour >= self.eod_hour:
            return "EOD"
        if self.london_start <= now <= self.london_end:
            return "LONDON"
        if self.ny_start <= now <= self.ny_end:
            return "NY"
        return "CLOSED"

    def minutes_to_next_session(self) -> int:
        """Minuti mancanti alla prossima kill zone (utile per logging)."""
        now = self.current_time_cet()
        now_minutes = now.hour * 60 + now.minute

        sessions_start = [
            self.london_start.hour * 60 + self.london_start.minute,
            self.ny_start.hour    * 60 + self.ny_start.minute,
        ]

        for s in sorted(sessions_start):
            if s > now_minutes:
                return s - now_minutes

        # Prossima sessione è domani (London)
        return (24 * 60 - now_minutes) + sessions_start[0]
