"""
Sistema di notifiche - Telegram e Discord.

Invia avvisi quando vengono trovate vulnerabilità durante la scansione.
"""

import json
import logging

import requests

logger = logging.getLogger("bugbounty_scanner")


class TelegramNotifier:
    """
    Invia notifiche su Telegram.

    Come configurare:
    1. Parla con @BotFather su Telegram e crea un bot
    2. Salva il token del bot
    3. Avvia una chat con il bot e ottieni il chat_id da:
       https://api.telegram.org/bot<TOKEN>/getUpdates
    4. Usa: --telegram-token TOKEN --telegram-chat CHAT_ID
    """

    def __init__(self, token, chat_id):
        self.token = token
        self.chat_id = chat_id
        self.api_url = f"https://api.telegram.org/bot{token}"

    def send(self, message):
        """Invia un messaggio su Telegram."""
        try:
            resp = requests.post(
                f"{self.api_url}/sendMessage",
                json={
                    "chat_id": self.chat_id,
                    "text": message,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                },
                timeout=10,
            )
            if resp.status_code != 200:
                logger.warning(f"  [Telegram] Errore invio: {resp.text[:200]}")
                return False
            return True
        except Exception as e:
            logger.warning(f"  [Telegram] Errore: {e}")
            return False

    def notify_finding(self, finding):
        """Notifica un singolo finding."""
        emoji = {
            "CRITICAL": "\xf0\x9f\x94\xb4",
            "HIGH": "\xf0\x9f\x9f\xa0",
            "MEDIUM": "\xf0\x9f\x9f\xa1",
            "LOW": "\xf0\x9f\x94\xb5",
            "INFO": "\xe2\x9a\xaa",
        }.get(finding.severity, "")

        msg = (
            f"{emoji} <b>[{finding.severity}] {finding.title}</b>\n\n"
            f"<b>URL:</b> <code>{finding.url}</code>\n"
            f"<b>Descrizione:</b> {finding.description[:200]}\n"
        )
        if finding.evidence:
            msg += f"<b>Evidenza:</b> <code>{finding.evidence[:150]}</code>\n"
        if finding.module:
            msg += f"<b>Modulo:</b> {finding.module}"

        return self.send(msg)

    def notify_scan_complete(self, scan_result):
        """Notifica il completamento della scansione."""
        summary = scan_result.summary
        sev = summary["by_severity"]

        msg = (
            f"<b>Scansione completata!</b>\n\n"
            f"<b>Target:</b> <code>{summary['target']}</code>\n"
            f"<b>Durata:</b> {summary['duration_seconds']}s\n"
            f"<b>Totale trovati:</b> {summary['total_findings']}\n\n"
        )

        for s in ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"]:
            count = sev.get(s, 0)
            if count > 0:
                msg += f"  {s}: {count}\n"

        return self.send(msg)


class DiscordNotifier:
    """
    Invia notifiche su Discord tramite webhook.

    Come configurare:
    1. Nel canale Discord: Impostazioni > Integrazioni > Webhook
    2. Crea un webhook e copia l'URL
    3. Usa: --discord-webhook URL
    """

    def __init__(self, webhook_url):
        self.webhook_url = webhook_url

    def send(self, message, embeds=None):
        """Invia un messaggio su Discord."""
        try:
            data = {"content": message}
            if embeds:
                data["embeds"] = embeds

            resp = requests.post(
                self.webhook_url,
                json=data,
                timeout=10,
            )
            if resp.status_code not in (200, 204):
                logger.warning(f"  [Discord] Errore invio: {resp.text[:200]}")
                return False
            return True
        except Exception as e:
            logger.warning(f"  [Discord] Errore: {e}")
            return False

    def notify_finding(self, finding):
        """Notifica un singolo finding con embed colorato."""
        color_map = {
            "CRITICAL": 0xFF0000,
            "HIGH": 0xFF8C00,
            "MEDIUM": 0xFFD700,
            "LOW": 0x4169E1,
            "INFO": 0x808080,
        }

        embed = {
            "title": f"[{finding.severity}] {finding.title}",
            "color": color_map.get(finding.severity, 0x808080),
            "fields": [
                {"name": "URL", "value": f"`{finding.url[:200]}`", "inline": False},
                {"name": "Descrizione", "value": finding.description[:200], "inline": False},
            ],
        }

        if finding.evidence:
            embed["fields"].append({
                "name": "Evidenza",
                "value": f"```{finding.evidence[:200]}```",
                "inline": False,
            })

        if finding.module:
            embed["fields"].append({
                "name": "Modulo",
                "value": finding.module,
                "inline": True,
            })

        return self.send("", embeds=[embed])

    def notify_scan_complete(self, scan_result):
        """Notifica il completamento della scansione."""
        summary = scan_result.summary
        sev = summary["by_severity"]

        sev_text = "\n".join(
            f"**{s}:** {sev.get(s, 0)}"
            for s in ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"]
            if sev.get(s, 0) > 0
        )

        embed = {
            "title": "Scansione Completata!",
            "color": 0x00FF00,
            "fields": [
                {"name": "Target", "value": f"`{summary['target']}`", "inline": True},
                {"name": "Durata", "value": f"{summary['duration_seconds']}s", "inline": True},
                {"name": "Totale", "value": str(summary['total_findings']), "inline": True},
                {"name": "Per gravita", "value": sev_text or "Nessuna vulnerabilita", "inline": False},
            ],
        }

        return self.send("", embeds=[embed])


class NotificationManager:
    """Gestisce tutti i canali di notifica."""

    def __init__(self):
        self.notifiers = []
        self.min_severity = "MEDIUM"  # Notifica solo da MEDIUM in su

    SEVERITY_ORDER = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"]

    def add_telegram(self, token, chat_id):
        self.notifiers.append(TelegramNotifier(token, chat_id))

    def add_discord(self, webhook_url):
        self.notifiers.append(DiscordNotifier(webhook_url))

    def set_min_severity(self, severity):
        self.min_severity = severity.upper()

    def _should_notify(self, severity):
        """Verifica se la gravità merita una notifica."""
        try:
            return (
                self.SEVERITY_ORDER.index(severity)
                <= self.SEVERITY_ORDER.index(self.min_severity)
            )
        except ValueError:
            return False

    def notify_finding(self, finding):
        """Notifica un finding a tutti i canali configurati."""
        if not self._should_notify(finding.severity):
            return

        for notifier in self.notifiers:
            try:
                notifier.notify_finding(finding)
            except Exception as e:
                logger.debug(f"  Errore notifica: {e}")

    def notify_scan_complete(self, scan_result):
        """Notifica il completamento della scansione."""
        for notifier in self.notifiers:
            try:
                notifier.notify_scan_complete(scan_result)
            except Exception as e:
                logger.debug(f"  Errore notifica completamento: {e}")

    @property
    def is_configured(self):
        return len(self.notifiers) > 0
