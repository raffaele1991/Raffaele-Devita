"""
News Filter
============
Blocca il trading N minuti prima/dopo eventi ad alto impatto.
La lista degli eventi viene aggiornata automaticamente all'avvio
da ForexFactory (solo se c'è connessione internet).
Se non c'è connessione usa una lista hardcoded degli eventi ricorrenti.
"""

import re
import json
import logging
import requests
from datetime import datetime, timedelta
from typing import List, Dict
import pytz

from trading_system import config

logger = logging.getLogger(__name__)

# ─── EVENTI RICORRENTI HARDCODED (fallback) ───────────────────────────────────
# Giorni della settimana e orari tipici degli eventi ad alto impatto (CET)
# Usato solo se il fetch da ForexFactory fallisce.

RECURRING_EVENTS = [
    # NFP – primo venerdì del mese, ore 14:30 CET
    {"name": "NFP",   "weekday": 4, "hour": 14, "minute": 30},
    # CPI USA – varia, tipicamente mercoledì alle 14:30
    {"name": "CPI",   "weekday": 2, "hour": 14, "minute": 30},
    # FOMC – variabile, tipicamente mercoledì alle 20:00
    {"name": "FOMC",  "weekday": 2, "hour": 20, "minute": 0},
    # BCE – tipicamente giovedì alle 14:15
    {"name": "BCE",   "weekday": 3, "hour": 14, "minute": 15},
    # Retail Sales USA – variabile, tipicamente ore 14:30
    {"name": "Retail Sales", "weekday": 2, "hour": 14, "minute": 30},
    # GDP USA
    {"name": "GDP",   "weekday": 3, "hour": 14, "minute": 30},
]


class NewsFilter:
    """
    Blocca il trading durante eventi macro ad alto impatto.
    """

    def __init__(self):
        self.tz      = pytz.timezone("Europe/Rome")
        self.buffer  = config.NEWS_BUFFER_MINUTES
        self.events: List[datetime] = []
        self._load_events()

    # ── CARICAMENTO EVENTI ────────────────────────────────────────────────────

    def _load_events(self):
        """Prova a scaricare eventi da ForexFactory, altrimenti usa fallback."""
        try:
            self._fetch_forexfactory()
            logger.info(f"[News] {len(self.events)} eventi caricati da ForexFactory")
        except Exception as e:
            logger.warning(f"[News] ForexFactory non disponibile ({e}), uso fallback")
            self._load_fallback()

    def _fetch_forexfactory(self):
        """
        ForexFactory fornisce un JSON pubblico del calendario.
        Prende solo gli eventi con impact='High' per i prossimi 7 giorni.
        """
        url     = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
        resp    = requests.get(url, timeout=10)
        resp.raise_for_status()
        data    = resp.json()

        self.events = []
        for ev in data:
            if ev.get("impact", "").lower() != "high":
                continue

            # Formato data: "01-27-2025" ora: "2:30pm"
            date_str = ev.get("date", "")
            time_str = ev.get("time", "")

            if not date_str or not time_str or time_str.lower() in ("all day", "tentative", ""):
                continue

            try:
                dt_naive = datetime.strptime(
                    f"{date_str} {time_str}", "%m-%d-%Y %I:%M%p"
                )
                # ForexFactory usa Eastern Time (ET)
                et_tz = pytz.timezone("America/New_York")
                dt_et = et_tz.localize(dt_naive)
                dt_cet = dt_et.astimezone(self.tz)
                self.events.append(dt_cet)
            except ValueError:
                continue

    def _load_fallback(self):
        """
        Genera eventi ricorrenti per i prossimi 14 giorni
        basandosi sui pattern storici.
        """
        self.events = []
        now = datetime.now(self.tz)
        for day_offset in range(14):
            dt = now + timedelta(days=day_offset)
            for ev in RECURRING_EVENTS:
                if dt.weekday() == ev["weekday"]:
                    event_dt = dt.replace(
                        hour=ev["hour"],
                        minute=ev["minute"],
                        second=0,
                        microsecond=0,
                    )
                    self.events.append(event_dt)

    def refresh(self):
        """Ricarica gli eventi (chiamare una volta al giorno)."""
        self._load_events()

    # ── CONTROLLO ─────────────────────────────────────────────────────────────

    def is_safe(self) -> bool:
        """
        True se non siamo vicini a nessun evento ad alto impatto.
        False se siamo entro NEWS_BUFFER_MINUTES da un evento.
        """
        now    = datetime.now(self.tz)
        buffer = timedelta(minutes=self.buffer)

        for ev in self.events:
            if abs((ev - now).total_seconds()) <= buffer.total_seconds():
                logger.info(f"[News] Blocco attivo: evento '{ev}' tra {int((ev-now).total_seconds()/60)} min")
                return False

        return True

    def next_blocked_event(self) -> str:
        """Restituisce info sul prossimo evento bloccante (per logging)."""
        now = datetime.now(self.tz)
        future = [(ev - now).total_seconds() for ev in self.events if ev > now]
        if not future:
            return "Nessun evento nelle prossime 2 settimane"
        mins = int(min(future) / 60)
        return f"Prossimo evento ad alto impatto tra {mins} minuti"
