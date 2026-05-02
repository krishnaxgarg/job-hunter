"""Top-level scraper runner. Orchestrates every source, applies filters,
saves new jobs to SQLite, and returns the new ones for downstream tailoring.

Run directly:
    python -m scrapers.run_all
"""

from __future__ import annotations

import logging
import os
import re
import sys
from pathlib import Path

import yaml

from .ats import ATSScraper
from .base import Job, Scraper, save_jobs
from .indeed import IndeedScraper
from .linkedin import LinkedInScraper
from .naukri import NaukriScraper
from .remoteok import RemoteOKScraper
from .wellfound import WellfoundScraper

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

PREFS_FILE = Path("resume/preferences.yaml")


def load_prefs() -> dict:
    return yaml.safe_load(PREFS_FILE.read_text())


# ─── Filters ─────────────────────────────────────────────────────────────────


def _title_ok(title: str, prefs: dict) -> bool:
    t = title.lower()
    if any(bad in t for bad in prefs["titles_exclude"]):
        return False
    return any(good in t for good in prefs["titles_include"])


def _location_ok(loc: str, prefs: dict) -> bool:
    if not loc:
        return True
    l = loc.lower()
    excl = [c.lower() for c in prefs["locations"].get("exclude_cities", [])]
    if any(c in l for c in excl):
        return False
    if prefs["locations"].get("india_any") and (
        "india" in l or any(city in l for city in (
            "bengaluru", "bangalore", "hyderabad", "pune", "mumbai", "delhi",
            "noida", "gurgaon", "gurugram", "chennai", "kolkata", "ahmedabad",
        ))
    ):
        return True
    if prefs["locations"].get("remote_global") and (
        "remote" in l or "anywhere" in l or "worldwide" in l
    ):
        return True
    return False


def _experience_ok(exp_str: str, prefs: dict) -> bool:
    """Try to parse "1-3 years" / "2+ years"; allow if unknown."""
    if not exp_str:
        return True
    nums = [int(n) for n in re.findall(r"\d+", exp_str)]
    if not nums:
        return True
    job_min = min(nums)
    job_max = max(nums) if len(nums) > 1 else job_min + 2
    pmin, pmax = prefs["experience_years"]["min"], prefs["experience_years"]["max"]
    return job_min <= pmax and job_max >= pmin


def _salary_ok(sal_str: str, prefs: dict) -> bool:
    """Allow if salary missing or >= prefs.min."""
    if not sal_str:
        return True
    nums = [int(n) for n in re.findall(r"\d+", sal_str)]
    if not nums:
        return True
    # Naukri uses LPA (Lakhs Per Annum) — values are like "8-15"
    # RemoteOK uses USD annual — convert roughly: $1 ≈ ₹83
    max_val = max(nums)
    if "lpa" in sal_str.lower() or "lakh" in sal_str.lower() or max_val < 200:
        # treat as LPA already
        return max_val >= prefs["salary_lpa"]["min"]
    # treat as USD
    lpa = max_val * 83 / 100000
    return lpa >= prefs["salary_lpa"]["min"]


def _is_target_company(company: str, prefs: dict) -> bool:
    c = company.lower()
    return any(t in c for t in prefs["target_companies"])


def filter_jobs(jobs: list[Job], prefs: dict) -> list[Job]:
    out: list[Job] = []
    for j in jobs:
        if not j.url or not j.title:
            continue
        # target companies bypass most filters (still must be a dev role)
        if _is_target_company(j.company, prefs):
            if _title_ok(j.title, prefs):
                out.append(j)
                continue
        if not _title_ok(j.title, prefs):
            continue
        if not _location_ok(j.location, prefs):
            continue
        if not _experience_ok(j.experience, prefs):
            continue
        if not _salary_ok(j.salary, prefs):
            continue
        out.append(j)
    return out


# ─── Main ────────────────────────────────────────────────────────────────────


SCRAPERS: list[type[Scraper]] = [
    ATSScraper,        # cleanest, run first
    RemoteOKScraper,
    IndeedScraper,
    WellfoundScraper,
    LinkedInScraper,
    NaukriScraper,
]


def main() -> int:
    prefs = load_prefs()
    all_jobs: list[Job] = []
    for cls in SCRAPERS:
        try:
            scraper = cls()
            jobs = scraper.fetch()
            all_jobs.extend(jobs)
        except Exception as e:    # noqa: BLE001
            logger.exception("Scraper %s crashed: %s", cls.__name__, e)
    logger.info("Total raw jobs collected: %d", len(all_jobs))

    filtered = filter_jobs(all_jobs, prefs)
    logger.info("After filters: %d jobs", len(filtered))

    new_jobs = save_jobs(filtered)
    logger.info("Net NEW jobs added to DB: %d", len(new_jobs))
    return len(new_jobs)


if __name__ == "__main__":
    sys.exit(0 if main() >= 0 else 1)
