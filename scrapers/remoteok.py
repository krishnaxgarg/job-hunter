"""RemoteOK official JSON API.

The easiest scraper of the bunch — they publish a public JSON feed.
"""

from __future__ import annotations

import logging

import requests

from .base import Job, Scraper, extract_experience, extract_tech

logger = logging.getLogger(__name__)


class RemoteOKScraper(Scraper):
    name = "remoteok"

    URL = "https://remoteok.com/api"

    def fetch(self) -> list[Job]:
        try:
            r = requests.get(self.URL, headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
            r.raise_for_status()
            data = r.json()
        except Exception as e:    # noqa: BLE001
            logger.warning("RemoteOK API failed: %s", e)
            return []

        out: list[Job] = []
        # First entry is metadata; skip it
        for j in data[1:]:
            try:
                title = j.get("position", "")
                if not any(t in title.lower() for t in ("engineer", "developer", "sde", "swe")):
                    continue
                desc = j.get("description", "")
                out.append(Job(
                    source="remoteok",
                    title=title,
                    company=j.get("company", ""),
                    location=j.get("location") or "Remote (Worldwide)",
                    url=j.get("url") or j.get("apply_url") or "",
                    description=desc[:8000],
                    salary=str(j.get("salary_min", "")) + (
                        f"-{j['salary_max']}" if j.get("salary_max") else ""
                    ),
                    posted_at=j.get("date", ""),
                    tech=j.get("tags", []) or extract_tech(title + " " + desc),
                    experience=extract_experience(desc),
                ))
            except Exception as e:    # noqa: BLE001
                logger.debug("RemoteOK entry parse failed: %s", e)
        logger.info("RemoteOK: %d jobs", len(out))
        return out
