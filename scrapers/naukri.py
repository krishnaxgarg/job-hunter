"""Naukri.com scraper.

Naukri exposes a JSON API on its job-listing page. We hit the search HTML page
and extract the embedded JSON. If they change the page structure this will need
updating; that's a known cost of free scraping.
"""

from __future__ import annotations

import json
import logging
import re
import time

import requests
from tenacity import retry, stop_after_attempt, wait_exponential

from .base import Job, Scraper, extract_tech

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "appid": "109",
    "systemid": "Naukri",
    "Referer": "https://www.naukri.com/",
}

# Naukri's internal search API
SEARCH_API = "https://www.naukri.com/jobapi/v3/search"

QUERIES = [
    {"keyword": "software engineer", "experience": "1", "noOfResults": "20"},
    {"keyword": "software developer", "experience": "2", "noOfResults": "20"},
    {"keyword": "backend developer", "experience": "2", "noOfResults": "20"},
    {"keyword": "full stack developer", "experience": "2", "noOfResults": "20"},
    {"keyword": "python developer", "experience": "2", "noOfResults": "20"},
    {"keyword": "java developer", "experience": "2", "noOfResults": "20"},
]


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=2, max=10))
def _fetch(params: dict) -> dict:
    r = requests.get(SEARCH_API, params=params, headers=HEADERS, timeout=20)
    if r.status_code != 200:
        raise RuntimeError(f"Naukri returned {r.status_code}")
    return r.json()


def _parse(data: dict) -> list[Job]:
    out: list[Job] = []
    for j in data.get("jobDetails", [])[:30]:
        try:
            title = j.get("title", "")
            company = j.get("companyName", "")
            location = ", ".join(j.get("placeholders", [{}])[0].get("label", "").split(",")[:2]) \
                if j.get("placeholders") else ""
            jd_url = "https://www.naukri.com/" + j.get("jdURL", "").lstrip("/")
            desc = j.get("jobDescription", "")
            salary = ""
            for ph in j.get("placeholders", []):
                if ph.get("type") == "salary":
                    salary = ph.get("label", "")
            exp = ""
            for ph in j.get("placeholders", []):
                if ph.get("type") == "experience":
                    exp = ph.get("label", "")
            tags = j.get("tagsAndSkills", "") or ""
            out.append(Job(
                source="naukri", title=title, company=company, location=location,
                url=jd_url, description=desc, salary=salary,
                posted_at=j.get("createdDate", ""),
                tech=extract_tech(tags + " " + desc + " " + title),
                experience=exp,
            ))
        except Exception as e:    # noqa: BLE001
            logger.debug("naukri parse error: %s", e)
    return out


class NaukriScraper(Scraper):
    name = "naukri"

    def fetch(self) -> list[Job]:
        jobs: list[Job] = []
        for q in QUERIES:
            try:
                data = _fetch(q)
                jobs.extend(_parse(data))
                time.sleep(1.5)
            except Exception as e:    # noqa: BLE001
                logger.warning("Naukri query %s failed: %s", q, e)
        logger.info("Naukri: %d jobs", len(jobs))
        return jobs
