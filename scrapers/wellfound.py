"""Wellfound (formerly AngelList Talent) scraper.

Wellfound's public job pages are server-rendered. We hit their search HTML
and extract the JSON island they embed for hydration.
"""

from __future__ import annotations

import json
import logging
import re
import time

import requests

from .base import Job, Scraper, extract_experience, extract_tech

logger = logging.getLogger(__name__)

URL = "https://wellfound.com/jobs?sort=newest&keywords={kw}"
HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "text/html"}

QUERIES = [
    "software-engineer", "backend-engineer", "frontend-engineer",
    "full-stack-engineer", "data-engineer", "machine-learning-engineer",
]


class WellfoundScraper(Scraper):
    name = "wellfound"

    def fetch(self) -> list[Job]:
        jobs: list[Job] = []
        for kw in QUERIES:
            try:
                r = requests.get(URL.format(kw=kw), headers=HEADERS, timeout=20)
                if r.status_code != 200:
                    continue
                # Pull JSON-LD JobPosting entries — most reliable
                for m in re.finditer(
                    r'<script type="application/ld\+json">(.*?)</script>',
                    r.text, re.S,
                ):
                    try:
                        d = json.loads(m.group(1))
                    except json.JSONDecodeError:
                        continue
                    items = d if isinstance(d, list) else [d]
                    for item in items:
                        if not isinstance(item, dict):
                            continue
                        if item.get("@type") != "JobPosting":
                            continue
                        desc = re.sub(r"<[^>]+>", " ", item.get("description", ""))
                        loc_obj = item.get("jobLocation", {})
                        if isinstance(loc_obj, list):
                            loc_obj = loc_obj[0] if loc_obj else {}
                        addr = loc_obj.get("address", {}) if isinstance(loc_obj, dict) else {}
                        location = ", ".join(filter(None, [
                            addr.get("addressLocality"), addr.get("addressCountry"),
                        ])) if isinstance(addr, dict) else ""
                        jobs.append(Job(
                            source="wellfound",
                            title=item.get("title", ""),
                            company=(item.get("hiringOrganization") or {}).get("name", ""),
                            location=location or "Remote",
                            url=item.get("url", ""),
                            description=desc[:8000],
                            posted_at=item.get("datePosted", ""),
                            tech=extract_tech(desc),
                            experience=extract_experience(desc),
                        ))
                time.sleep(1.5)
            except Exception as e:    # noqa: BLE001
                logger.warning("Wellfound %s failed: %s", kw, e)
        logger.info("Wellfound: %d jobs", len(jobs))
        return jobs
