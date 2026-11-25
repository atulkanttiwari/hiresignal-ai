# Free Telegram Bot alert for new eligible jobs or failures
import html
import time
from typing import List

import requests

from config.settings import get_settings
from models.schemas import ProcessedJob
from utils.logger import get_logger

logger = get_logger(__name__)


class TelegramNotifier:
    def __init__(self):
        settings = get_settings()
        self.bot_token = getattr(settings, "TELEGRAM_BOT_TOKEN", None)
        self.chat_id = getattr(settings, "TELEGRAM_CHAT_ID", None)
        self.min_score = getattr(settings, "MIN_MATCH_SCORE", 75)
        self.enabled = bool(self.bot_token and self.chat_id)

        if not self.enabled:
            logger.warning(
                "TelegramNotifier disabled: TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID missing in .env"
            )

    def _format_message(self, job: ProcessedJob) -> str:
        """Formats a high-match job into a clean Telegram HTML card."""
        title = html.escape(job.title)
        company = html.escape(job.company_canonical)
        location = html.escape(job.location or "India / Not specified")
        reasoning = html.escape(job.reasoning or "")

        matching = ", ".join(html.escape(s) for s in job.matching_skills) or "—"
        missing = ", ".join(html.escape(s) for s in job.missing_skills) or "None"
        fresher_tag = "🎓 Fresher-Friendly" if job.is_fresher_friendly else "💼 Experienced"
        remote_tag = " | 🌐 Remote" if job.is_remote else ""

        return (
            f"🎯 <b>{job.match_score}/100 Match — {title}</b>\n"
            f"🏢 <b>{company}</b> | 📍 {location}{remote_tag}\n"
            f"{fresher_tag} | Source: <code>{html.escape(job.source)}</code>\n\n"
            f"📝 {reasoning}\n\n"
            f"✅ <b>Matching:</b> {matching}\n"
            f"⚠️ <b>Missing:</b> {missing}\n\n"
            f"🔗 <a href=\"{job.url}\">Apply Now</a>"
        )

    def send_alerts(self, jobs: List[ProcessedJob]) -> int:
        """Sends Telegram alerts for all newly saved jobs meeting MIN_MATCH_SCORE."""
        if not self.enabled:
            return 0

        high_matches = [j for j in jobs if j.match_score >= self.min_score and j.is_fresher_friendly]
        if not high_matches:
            logger.info(f"No new jobs met the Telegram alert threshold (>= {self.min_score}).")
            return 0

        api_url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        sent_count = 0

        for job in high_matches:
            payload = {
                "chat_id": self.chat_id,
                "text": self._format_message(job),
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            }
            try:
                resp = requests.post(api_url, json=payload, timeout=10)
                resp.raise_for_status()
                sent_count += 1
                time.sleep(0.5)  # Gentle pacing for Telegram rate limits
            except Exception as e:
                logger.warning(f"Failed to send Telegram alert for '{job.title}': {e}")

        logger.info(f"Sent {sent_count} Telegram job alerts (threshold >= {self.min_score}).")
        return sent_count