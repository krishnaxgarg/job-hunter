"""Use Google Gemini (free tier) to tailor master_resume.json bullets to a JD.

Returns a *new* dict in the same shape as master_resume.json, with experience
and project bullets rewritten + expanded to highlight overlap with the JD.

Free-tier limits (May 2026): gemini-2.5-flash → generous RPM/RPD on AI Studio.
Plenty for 25 jobs/day.
"""

from __future__ import annotations

import json
import logging
import os
import time
from copy import deepcopy

from google import genai
from google.genai import types

logger = logging.getLogger(__name__)

MODEL_NAME = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")

PROMPT_TEMPLATE = """You are a senior career coach tailoring a candidate's resume to a
specific job description. The candidate will read your output before applying — it must
sound like THEY wrote it, not like a generic AI-polished resume. But it should also be
clearly stronger than their starting draft: better targeted, richer detail, more
keywords from the JD, and bullets that actually compete with the strongest applicants
for this role.

I will give you:
1. The candidate's master resume (JSON — the SOURCE OF TRUTH for *facts*).
2. A target job description.

==============================
WHAT YOU SHOULD DO — be active
==============================
- Add a brand new "summary" field (2-3 sentences, first-person-ish but written in third
  voice — e.g. "Full-stack engineer with 1 year shipping production Django + Flutter
  apps at a health-tech startup, plus competitive-programming background (Codeforces
  Expert, LeetCode Guardian). Looking for backend / full-stack roles where ...").
  Pull keywords from the JD into this summary naturally.
- For EVERY existing bullet, EXPAND it: add the implied technical specifics that
  someone working with the listed tech stack would obviously have done. Examples of
  fair expansion (these are inferences from the tech, not invented facts):
    * "Built backend services with Django" → "Designed and shipped Django REST APIs
      using DRF serializers, class-based views, ORM-level query optimization, and JWT
      auth, exposing endpoints consumed by Flutter clients."
    * "Cut data retrieval time by 50%" → keep the metric, but add the *technique*:
      "...by adding indexed lookups, replacing N+1 ORM patterns with select_related,
      and batching reads."
- Reorder bullets so the most JD-relevant come first.
- Reorder skill categories so JD-required tech appears earlier.
- ADD up to 2 NEW bullets per role IF they're directly implied by the role's tech
  stack and the JD's requirements. Example: if the role uses Django + PostgreSQL and
  the JD emphasizes "database performance", you may add a bullet about query tuning
  or indexing strategies in their existing Django role — because anyone shipping
  Django to production touches that.
- Pull the candidate's "achievements" (GFG, Codeforces, LeetCode etc.) into the
  output JSON's "achievements" field if they're not already there. These signal
  problem-solving ability and matter for SDE roles.
- Pick the 2-3 MOST relevant projects out of all projects.
- If JD lists tech the candidate has used elsewhere in the resume, surface it in the
  most relevant bullet's tech list and skills section.

=================================
WHAT YOU MAY NOT DO — hard limits
=================================
- DO NOT invent companies, job titles, employment dates, project names, or
  certifications.
- DO NOT invent specific numeric metrics that aren't in the master resume. Saying
  "improved performance" or "reduced latency" without a number is fine; saying
  "cut p99 from 800ms to 120ms" when no number exists in the master = forbidden.
- DO NOT inflate existing metrics (don't change "30%" to "70%").
- DO NOT claim the candidate worked on tech they have no exposure to anywhere in the
  master resume — even adjacently.
- DO NOT add fake awards, scholarships, publications, or talks.

==========
STYLE
==========
- Real-person voice. Banned words: "leveraged", "synergized", "spearheaded",
  "utilized", "orchestrated", "championed", "passionate", "rockstar", "ninja",
  "pivotal", "robust", "seamless", "cutting-edge", "world-class", "best-in-class",
  "delve", "tapestry".
- Plain verbs: "built", "shipped", "wrote", "fixed", "owned", "ran", "moved", "cut",
  "launched", "rewrote", "designed", "scaled".
- Bullets should each pack a verb + concrete artifact + technique or outcome.
- Vary bullet length — that reads more human than uniform 2-line bullets.

================================
OUTPUT SCHEMA
================================
Return STRICT JSON — no markdown fence, no commentary. Same shape as input PLUS a new
top-level "summary" string field. Keep all top-level fields from input. Example shape:

{{
  "name": "...", "phone": "...", "email": "...", "linkedin": "...", "github": "...",
  "location": "...",
  "summary": "...",
  "education": [...],
  "experience": [{{"title": "...", "company": "...", "location": "...", "dates": "...", "bullets": [...], "tech": [...]}}],
  "projects": [...],
  "skills": {{"languages": [...], "frameworks": [...], "databases": [...], "cloud_devops": [...], "other": [...]}},
  "achievements": [...]
}}

=== MASTER RESUME ===
{resume_json}

=== JOB DESCRIPTION ===
Role: {role}
Company: {company}
JD:
{jd}

Return the tailored resume JSON now:"""


def _client() -> genai.Client:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY env var not set")
    return genai.Client(api_key=api_key)


def tailor(master_resume: dict, role: str, company: str, jd: str) -> dict:
    client = _client()
    prompt = PROMPT_TEMPLATE.format(
        resume_json=json.dumps(master_resume, indent=2),
        role=role, company=company, jd=jd[:6000],
    )
    for attempt in range(3):
        try:
            resp = client.models.generate_content(
                model=MODEL_NAME,
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.6,                       # bumped up for more creativity
                    response_mime_type="application/json",
                ),
            )
            text = (resp.text or "").strip()
            if not text:
                raise ValueError("empty response from Gemini")
            tailored = json.loads(text)
            if not tailored.get("name") or not tailored.get("experience"):
                raise ValueError("tailored resume missing required fields")
            # carry over master fields the AI sometimes drops
            for k in ("phone", "email", "linkedin", "github", "location"):
                tailored.setdefault(k, master_resume.get(k, ""))
            return tailored
        except json.JSONDecodeError as e:
            logger.warning("Gemini returned non-JSON (attempt %d): %s", attempt + 1, e)
            time.sleep(3)
        except Exception as e:    # noqa: BLE001
            logger.warning("Gemini call failed (attempt %d): %s", attempt + 1, e)
            time.sleep(5)
    logger.error(
        "All Gemini attempts failed for %s @ %s — falling back to master resume",
        role, company,
    )
    return deepcopy(master_resume)
