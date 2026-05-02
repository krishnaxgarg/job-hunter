"""Push tailored jobs to the user's Telegram chat with Apply / Skip buttons.

Run after `scrapers.run_all`. Reads unsent jobs from SQLite, tailors a resume
PDF for each (via Gemini + LaTeX), then posts:
    - photo-style card with title/company/location/salary
    - the tailored PDF as a file attachment
    - inline buttons: Apply / Skip / View JD

The button callbacks are handled by the Cloudflare Worker (worker/src/index.js)
so they keep working between hourly GitHub Action runs.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

import requests
import yaml

# allow running as `python -m bot.send_jobs` from project root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scrapers.base import (  # noqa: E402
    Job, daily_sent_count, mark_sent, unsent_jobs,
)
from tailor.gemini_tailor import tailor  # noqa: E402
from tailor.latex_builder import build_for_job  # noqa: E402

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
TG = f"https://api.telegram.org/bot{BOT_TOKEN}"

PREFS = yaml.safe_load(Path("resume/preferences.yaml").read_text())
MASTER_RESUME = json.loads(Path("resume/master_resume.json").read_text())

# strip _README from master resume so it doesn't pollute prompts
MASTER_RESUME.pop("_README", None)


# ─── Telegram helpers ────────────────────────────────────────────────────────


def _send_message(text: str, reply_markup: dict | None = None) -> dict:
    payload = {
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    if reply_markup:
        payload["reply_markup"] = json.dumps(reply_markup)
    r = requests.post(f"{TG}/sendMessage", data=payload, timeout=20)
    r.raise_for_status()
    return r.json()


def _send_document(path: Path, caption: str = "") -> dict:
    with path.open("rb") as f:
        r = requests.post(
            f"{TG}/sendDocument",
            data={"chat_id": CHAT_ID, "caption": caption[:1000], "parse_mode": "HTML"},
            files={"document": (path.name, f, "application/pdf")},
            timeout=60,
        )
    r.raise_for_status()
    return r.json()


# ─── Card formatting ─────────────────────────────────────────────────────────


def _format_card(j: Job) -> str:
    salary = f" · 💰 {j.salary}" if j.salary else ""
    posted = f" · 🗓 {j.posted_at[:10]}" if j.posted_at else ""
    tech = ", ".join(j.tech[:6]) if j.tech else "—"
    desc = j.description.strip().replace("\n", " ")[:400]
    if len(j.description) > 400:
        desc += "…"
    return (
        f"🟢 <b>{_e(j.title)}</b> — <b>{_e(j.company)}</b>\n"
        f"📍 {_e(j.location or 'N/A')}{salary}{posted}\n"
        f"🛠 <i>{_e(tech)}</i>\n"
        f"🌐 <i>via {j.source}</i>\n\n"
        f"📝 {_e(desc)}"
    )


def _e(text: str) -> str:
    """Telegram HTML-escape."""
    return (text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _buttons_for(j: Job) -> dict:
    return {
        "inline_keyboard": [[
            {"text": "✅ Apply", "callback_data": f"apply:{j.job_id}"},
            {"text": "❌ Skip", "callback_data": f"skip:{j.job_id}"},
            {"text": "🔗 JD", "url": j.url},
        ]]
    }


# ─── Main ────────────────────────────────────────────────────────────────────


def main() -> None:
    daily_cap = PREFS.get("daily_limit", 25)
    hourly_cap = PREFS.get("hourly_limit", 5)

    sent_today = daily_sent_count()
    if sent_today >= daily_cap:
        logger.info("Daily cap %d already reached — exiting", daily_cap)
        return

    budget = min(hourly_cap, daily_cap - sent_today)
    jobs = unsent_jobs(limit=budget)
    if not jobs:
        logger.info("No new jobs to send.")
        return

    logger.info("Sending %d jobs to Telegram (sent today: %d, daily cap: %d)",
                len(jobs), sent_today, daily_cap)

    pdf_dir = Path("db/pdfs")
    pdf_dir.mkdir(parents=True, exist_ok=True)

    for j in jobs:
        try:
            # 1) Tailor resume via Gemini
            logger.info("Tailoring for: %s @ %s", j.title, j.company)
            tailored = tailor(MASTER_RESUME, j.title, j.company, j.description or j.title)

            # 2) Build PDF
            pdf_path = build_for_job(tailored, j.job_id, pdf_dir)

            # 3) Send card
            card = _format_card(j)
            _send_message(card, reply_markup=_buttons_for(j))

            # 4) Send PDF (if compile worked)
            if pdf_path and pdf_path.exists():
                fname = f"{tailored.get('name','resume').replace(' ', '_')}_{j.company.replace(' ', '_')[:25]}.pdf"
                # rename for nicer download name
                renamed = pdf_path.with_name(fname)
                pdf_path.rename(renamed)
                _send_document(renamed, caption=f"Tailored resume for <b>{_e(j.company)}</b>")
            else:
                _send_message("⚠️ Resume PDF compile failed for this job — apply with your default resume.")

            # 5) Mark sent
            mark_sent(j.job_id)
        except Exception as e:    # noqa: BLE001
            logger.exception("Failed to send job %s: %s", j.job_id, e)


if __name__ == "__main__":
    main()
