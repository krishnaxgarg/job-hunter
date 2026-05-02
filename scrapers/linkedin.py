"""LinkedIn scraper.

LinkedIn aggressively blocks scrapers. We use the **public guest jobs search**
endpoint (no login, returns HTML cards). It's rate-limited and may break — we
catch and log failures so the rest of the pipeline keeps working.

We do NOT log into LinkedIn or post anywhere on your behalf.
"""

from __future__ import annotations

import logging
import time
from urllib.parse import urlencode

import requests
from bs4 import BeautifulSoup
from tenacity import retry, stop_after_attempt, wait_exponential

from .base import Job, Scraper, extract_experience, extract_tech

logger = logging.getLogger(__name__)

GUEST_SEARCH = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-IN,en;q=0.9",
}

QUERIES = [
    {"keywords": "software engineer", "location": "India", "f_TPR": "r3600"},
    {"keywords": "software developer", "location": "India", "f_TPR": "r3600"},
    {"keywords": "backend engineer", "location": "India", "f_TPR": "r3600"},
    {"keywords": "frontend engineer", "location": "India", "f_TPR": "r3600"},
    {"keywords": "full stack engineer", "location": "India", "f_TPR": "r3600"},
    {"keywords": "data engineer", "location": "India", "f_TPR": "r3600"},
    {"keywords": "machine learning engineer", "location": "India", "f_TPR": "r3600"},
    # remote global SDE
    {"keywords": "software engineer", "location": "Worldwide",
     "f_TPR": "r3600", "f_WT": "2"},   # WT=2 → remote
]


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=2, max=10))
def _fetch(params: dict) -> str:
    r = requests.get(GUEST_SEARCH, params=params, headers=HEADERS, timeout=20)
    r.raise_for_status()
    return r.text


def _parse_card(card) -> Job | None:
    try:
        a = card.find("a", class_="base-card__full-link") or card.find("a")
        title_el = card.find("h3")
        company_el = card.find("h4")
        location_el = card.find("span", class_="job-search-card__location")
        time_el = card.find("time")
        if not (a and title_el and company_el):
            return None
        url = a.get("href", "").split("?")[0]
        title = title_el.get_text(strip=True)
        company = company_el.get_text(strip=True)
        location = location_el.get_text(strip=True) if location_el else ""
        posted = time_el.get("datetime", "") if time_el else ""
        # JD is fetched lazily — leave empty for now to keep this fast
        return Job(
            source="linkedin", title=title, company=company, location=location,
            url=url, description="", posted_at=posted,
        )
    except Exception as e:   # noqa: BLE001
        logger.debug("LinkedIn card parse failed: %s", e)
        return None


def _enrich_jd(job: Job) -> None:
    """Fetch the JD page once we know we want this job."""
    try:
        r = requests.get(job.url, headers=HEADERS, timeout=20)
        if r.status_code != 200:
            return
        soup = BeautifulSoup(r.text, "lxml")
        desc_el = soup.find("div", class_="show-more-less-html__markup")
        if desc_el:
            job.description = desc_el.get_text("\n", strip=True)[:8000]
        job.tech = extract_tech(job.description or job.title)
        job.experience = extract_experience(job.description)
    except Exception as e:    # noqa: BLE001
        logger.debug("LinkedIn enrich failed for %s: %s", job.url, e)


class LinkedInScraper(Scraper):
    name = "linkedin"

    def fetch(self) -> list[Job]:
        jobs: list[Job] = []
        for q in QUERIES:
            try:
                html = _fetch({**q, "start": 0})
                soup = BeautifulSoup(html, "lxml")
                cards = soup.find_all("div", class_="base-card") or soup.find_all("li")
                for c in cards[:25]:
                    j = _parse_card(c)
                    if j:
                        jobs.append(j)
                time.sleep(2)   # be polite
            except Exception as e:   # noqa: BLE001
                logger.warning("LinkedIn query %s failed: %s", q, e)
        # de-dupe within this batch by URL
        seen_urls = set()
        deduped: list[Job] = []
        for j in jobs:
            if j.url and j.url not in seen_urls:
                seen_urls.add(j.url)
                deduped.append(j)
        # enrich first 30 (others get enriched lazily later if user wants)
        for j in deduped[:30]:
            _enrich_jd(j)
            time.sleep(0.5)
        logger.info("LinkedIn: %d jobs", len(deduped))
        return deduped
