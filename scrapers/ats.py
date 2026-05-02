"""ATS scraper — Greenhouse, Lever, Ashby.

These three ATSes power the careers pages of MOST top tech companies (Stripe,
Razorpay, Postman, Atlassian, Notion, Airbnb, etc.) and they all expose
clean public JSON APIs. This is the highest-quality data source.

Add/remove companies in COMPANIES below.
"""

from __future__ import annotations

import logging
import time

import requests

from .base import Job, Scraper, extract_experience, extract_tech

logger = logging.getLogger(__name__)

# (slug, ats_type)
COMPANIES: list[tuple[str, str]] = [
    # Greenhouse
    ("razorpay", "greenhouse"),
    ("stripe", "greenhouse"),
    ("airbnb", "greenhouse"),
    ("zomato", "greenhouse"),
    ("postman", "greenhouse"),
    ("freshworks", "greenhouse"),
    ("browserstack", "greenhouse"),
    ("cred", "greenhouse"),
    ("phonepe", "greenhouse"),
    ("groww", "greenhouse"),
    ("meesho", "greenhouse"),
    ("flipkart", "greenhouse"),
    ("swiggy", "greenhouse"),
    ("uber", "greenhouse"),
    ("doordash", "greenhouse"),
    ("airtable", "greenhouse"),
    ("notion", "greenhouse"),
    ("figma", "greenhouse"),
    ("vercel", "greenhouse"),
    ("supabase", "greenhouse"),

    # Lever
    ("netflix", "lever"),
    ("plaid", "lever"),
    ("github", "lever"),
    ("hashicorp", "lever"),
    ("ramp", "lever"),
    ("retool", "lever"),
    ("scale", "lever"),
    ("brex", "lever"),

    # Ashby
    ("anthropic", "ashby"),
    ("openai", "ashby"),
    ("linear", "ashby"),
    ("posthog", "ashby"),
    ("clerk", "ashby"),
    ("modal", "ashby"),
]

KEYWORDS = (
    "engineer", "developer", "sde", "swe", "programmer",
    "platform", "infrastructure", "devops", "site reliability",
    "data engineer", "machine learning", "ml engineer",
)


def _is_relevant(title: str) -> bool:
    t = title.lower()
    if any(b in t for b in ("intern", "principal", "staff", "director", "manager", "lead",
                             "vp", "head of")):
        return False
    return any(k in t for k in KEYWORDS)


# ─── Greenhouse ──────────────────────────────────────────────────────────────


def _greenhouse(slug: str) -> list[Job]:
    out: list[Job] = []
    try:
        r = requests.get(
            f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true",
            timeout=20,
        )
        if r.status_code != 200:
            return []
        for j in r.json().get("jobs", []):
            title = j.get("title", "")
            if not _is_relevant(title):
                continue
            content = j.get("content", "")  # HTML
            import re as _re
            desc = _re.sub(r"<[^>]+>", " ", content)
            location = (j.get("location") or {}).get("name", "")
            out.append(Job(
                source=f"greenhouse/{slug}",
                title=title, company=slug.capitalize(), location=location,
                url=j.get("absolute_url", ""), description=desc[:8000],
                posted_at=j.get("updated_at", ""),
                tech=extract_tech(title + " " + desc),
                experience=extract_experience(desc),
                ats="greenhouse",
            ))
    except Exception as e:    # noqa: BLE001
        logger.debug("Greenhouse %s failed: %s", slug, e)
    return out


# ─── Lever ───────────────────────────────────────────────────────────────────


def _lever(slug: str) -> list[Job]:
    out: list[Job] = []
    try:
        r = requests.get(f"https://api.lever.co/v0/postings/{slug}?mode=json", timeout=20)
        if r.status_code != 200:
            return []
        for j in r.json():
            title = j.get("text", "")
            if not _is_relevant(title):
                continue
            desc_lists = j.get("lists", []) or []
            desc = " ".join(
                (lst.get("text", "") or "") + " " + (lst.get("content", "") or "")
                for lst in desc_lists
            )
            import re as _re
            desc = _re.sub(r"<[^>]+>", " ", desc + " " + j.get("descriptionPlain", ""))
            cats = j.get("categories", {}) or {}
            location = cats.get("location", "")
            out.append(Job(
                source=f"lever/{slug}",
                title=title, company=slug.capitalize(), location=location,
                url=j.get("hostedUrl", ""), description=desc[:8000],
                posted_at=str(j.get("createdAt", "")),
                tech=extract_tech(title + " " + desc),
                experience=extract_experience(desc),
                ats="lever",
            ))
    except Exception as e:    # noqa: BLE001
        logger.debug("Lever %s failed: %s", slug, e)
    return out


# ─── Ashby ───────────────────────────────────────────────────────────────────


def _ashby(slug: str) -> list[Job]:
    out: list[Job] = []
    try:
        r = requests.post(
            f"https://api.ashbyhq.com/posting-api/job-board/{slug}",
            json={"includeCompensation": True}, timeout=20,
        )
        if r.status_code != 200:
            return []
        for j in r.json().get("jobs", []):
            title = j.get("title", "")
            if not _is_relevant(title):
                continue
            desc = j.get("descriptionPlain", "") or ""
            out.append(Job(
                source=f"ashby/{slug}",
                title=title, company=slug.capitalize(),
                location=j.get("locationName", ""),
                url=j.get("jobUrl", ""), description=desc[:8000],
                posted_at=j.get("publishedDate", ""),
                tech=extract_tech(title + " " + desc),
                experience=extract_experience(desc),
                ats="ashby",
            ))
    except Exception as e:    # noqa: BLE001
        logger.debug("Ashby %s failed: %s", slug, e)
    return out


_DISPATCH = {"greenhouse": _greenhouse, "lever": _lever, "ashby": _ashby}


class ATSScraper(Scraper):
    name = "ats"

    def fetch(self) -> list[Job]:
        jobs: list[Job] = []
        for slug, ats in COMPANIES:
            fn = _DISPATCH.get(ats)
            if not fn:
                continue
            jobs.extend(fn(slug))
            time.sleep(0.4)
        logger.info("ATS: %d jobs across %d companies", len(jobs), len(COMPANIES))
        return jobs
