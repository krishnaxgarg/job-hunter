"""Shared types, DB helpers, and the base Scraper class.

All scrapers return a list of `Job` objects. `db.py` (used here) handles
dedupe across runs so we never resend the same posting twice.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import sqlite3
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterable

logger = logging.getLogger(__name__)

DB_PATH = Path(os.environ.get("JOB_DB_PATH", "db/jobs.db"))


@dataclass
class Job:
    source: str               # "linkedin", "naukri", ...
    title: str
    company: str
    location: str
    url: str                  # canonical apply URL
    description: str          # full JD text
    salary: str = ""          # raw string, e.g. "₹15-30 LPA" or ""
    posted_at: str = ""       # ISO date string if known
    tech: list[str] = field(default_factory=list)
    experience: str = ""      # raw string, e.g. "1-3 years"
    ats: str = ""             # "greenhouse" / "lever" / "ashby" / ""

    @property
    def job_id(self) -> str:
        """Stable hash for dedupe — based on company+title+url so re-posts collapse."""
        key = f"{self.company.lower().strip()}|{self.title.lower().strip()}|{self.url}"
        return hashlib.sha1(key.encode()).hexdigest()[:16]


# ─── DB layer ────────────────────────────────────────────────────────────────


def _conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB_PATH)
    c.execute(
        """CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                source TEXT,
                title TEXT,
                company TEXT,
                location TEXT,
                url TEXT,
                description TEXT,
                salary TEXT,
                posted_at TEXT,
                tech TEXT,
                experience TEXT,
                ats TEXT,
                seen_at TEXT,
                sent_at TEXT,
                user_action TEXT,    -- 'apply' / 'skip' / NULL
                applied_at TEXT
        )"""
    )
    return c


def already_seen(job_ids: Iterable[str]) -> set[str]:
    """Return the subset of job_ids that already exist in the DB."""
    ids = list(job_ids)
    if not ids:
        return set()
    with _conn() as c:
        rows = c.execute(
            f"SELECT id FROM jobs WHERE id IN ({','.join('?' * len(ids))})",
            ids,
        ).fetchall()
    return {r[0] for r in rows}


def save_jobs(jobs: list[Job]) -> list[Job]:
    """Insert new jobs; return only the ones that were genuinely new."""
    if not jobs:
        return []
    new_jobs: list[Job] = []
    with _conn() as c:
        for j in jobs:
            row = c.execute("SELECT 1 FROM jobs WHERE id = ?", (j.job_id,)).fetchone()
            if row:
                continue
            c.execute(
                """INSERT INTO jobs(id,source,title,company,location,url,description,
                       salary,posted_at,tech,experience,ats,seen_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    j.job_id, j.source, j.title, j.company, j.location, j.url,
                    j.description, j.salary, j.posted_at, ",".join(j.tech),
                    j.experience, j.ats, datetime.utcnow().isoformat(),
                ),
            )
            new_jobs.append(j)
    logger.info("Stored %d new jobs (skipped %d duplicates)",
                len(new_jobs), len(jobs) - len(new_jobs))
    return new_jobs


def unsent_jobs(limit: int = 5) -> list[Job]:
    with _conn() as c:
        rows = c.execute(
            """SELECT source,title,company,location,url,description,salary,posted_at,
                      tech,experience,ats
               FROM jobs
               WHERE sent_at IS NULL
               ORDER BY seen_at DESC LIMIT ?""",
            (limit,),
        ).fetchall()
    return [
        Job(
            source=r[0], title=r[1], company=r[2], location=r[3], url=r[4],
            description=r[5], salary=r[6], posted_at=r[7],
            tech=r[8].split(",") if r[8] else [], experience=r[9], ats=r[10],
        )
        for r in rows
    ]


def mark_sent(job_id: str) -> None:
    with _conn() as c:
        c.execute("UPDATE jobs SET sent_at = ? WHERE id = ?",
                  (datetime.utcnow().isoformat(), job_id))


def daily_sent_count() -> int:
    today = datetime.utcnow().date().isoformat()
    with _conn() as c:
        row = c.execute(
            "SELECT COUNT(*) FROM jobs WHERE substr(sent_at,1,10) = ?", (today,)
        ).fetchone()
    return row[0] if row else 0


# ─── Base scraper ────────────────────────────────────────────────────────────


class Scraper:
    name: str = "base"

    def fetch(self) -> list[Job]:
        raise NotImplementedError


# ─── Helpers shared by scrapers ──────────────────────────────────────────────


_TECH_PATTERNS = [
    r"\bpython\b", r"\bjava\b", r"\bgo(lang)?\b", r"\bjavascript\b",
    r"\btypescript\b", r"\breact\b", r"\bnode\.?js\b", r"\bdjango\b",
    r"\bflask\b", r"\bfastapi\b", r"\bspring( ?boot)?\b", r"\bpostgres(ql)?\b",
    r"\bmysql\b", r"\bredis\b", r"\bmongodb\b", r"\baws\b", r"\bgcp\b",
    r"\bazure\b", r"\bkubernetes\b", r"\bdocker\b", r"\bkafka\b", r"\bgraphql\b",
    r"\bgrpc\b", r"\brest( apis)?\b", r"\bnext\.?js\b", r"\bvue\b",
    r"\bangular\b", r"\bml\b", r"\bnlp\b", r"\bllm\b", r"\btensorflow\b",
    r"\bpytorch\b", r"\bsql\b",
]


def extract_tech(text: str) -> list[str]:
    """Return de-duped list of tech keywords found in text."""
    text = text.lower()
    found: list[str] = []
    for pat in _TECH_PATTERNS:
        m = re.search(pat, text)
        if m:
            tag = m.group(0).replace(".", "").replace(" ", "").lower()
            if tag not in found:
                found.append(tag)
    return found


def extract_experience(text: str) -> str:
    """Pull a "1-3 years" / "2+ years" string from JD text."""
    m = re.search(r"(\d+\s*[-–to]+\s*\d+\+?\s*years?|\d+\+?\s*years?)", text, re.I)
    return m.group(0) if m else ""
