"""Indeed India scraper via RSS feed.

Indeed exposes an RSS feed for any search query — the most reliable, no-block
data source for India jobs. Format:
  https://in.indeed.com/rss?q=software+engineer&l=India&fromage=1&sort=date
"""

from __future__ import annotations

import logging
import time
from urllib.parse import quote_plus

import feedparser
import requests
from bs4 import BeautifulSoup

from .base import Job, Scraper, extract_experience, extract_tech

logger = logging.getLogger(__name__)

BASE = "https://in.indeed.com/rss"

QUERIES = [
    ("software engineer", "India"),
    ("software developer", "India"),
    ("backend developer", "India"),
    ("full stack developer", "India"),
    ("python developer", "India"),
    ("java developer", "India"),
    ("data engineer", "India"),
    ("ml engineer", "India"),
    ("software engineer", "Remote"),
]


def _build_url(q: str, l: str) -> str:
    return f"{BASE}?q={quote_plus(q)}&l={quote_plus(l)}&fromage=1&sort=date"


def _fetch_jd(url: str) -> str:
    try:
        r = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code != 200:
            return ""
        soup = BeautifulSoup(r.text, "lxml")
        el = soup.find(id="jobDescriptionText")
        return el.get_text("\n", strip=True)[:8000] if el else ""
    except Exception:    # noqa: BLE001
        return ""


class IndeedScraper(Scraper):
    name = "indeed"

    def fetch(self) -> list[Job]:
        jobs: list[Job] = []
        for q, loc in QUERIES:
            try:
                feed = feedparser.parse(_build_url(q, loc))
                for entry in feed.entries[:20]:
                    title_full = entry.title          # "Software Engineer - Acme - Bengaluru"
                    parts = [p.strip() for p in title_full.rsplit(" - ", 2)]
                    if len(parts) >= 3:
                        title, company, location = parts[0], parts[1], parts[2]
                    else:
                        title, company, location = title_full, "", loc
                    desc = entry.summary if hasattr(entry, "summary") else ""
                    jobs.append(Job(
                        source="indeed", title=title, company=company,
                        location=location, url=entry.link, description=desc,
                        posted_at=entry.get("published", ""),
                        tech=extract_tech(title + " " + desc),
                        experience=extract_experience(desc),
                    ))
                time.sleep(1)
            except Exception as e:    # noqa: BLE001
                logger.warning("Indeed query (%s, %s) failed: %s", q, loc, e)
        # enrich top 20 JDs (Indeed RSS only gives a snippet)
        for j in jobs[:20]:
            if not j.description or len(j.description) < 200:
                full = _fetch_jd(j.url)
                if full:
                    j.description = full
                    j.tech = extract_tech(full)
                    j.experience = extract_experience(full)
                time.sleep(0.4)
        logger.info("Indeed: %d jobs", len(jobs))
        return jobs
