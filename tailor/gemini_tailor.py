"""Use Google Gemini (free tier) to tailor master_resume.json bullets to a JD.

Returns a *new* dict in the same shape as master_resume.json, with experience
and project bullets rewritten to highlight overlap with the JD.

Free-tier limits (May 2026): gemini-2.5-flash → generous RPM/RPD on the
AI Studio free tier. Plenty for 25 jobs/day.
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

PROMPT_TEMPLATE = """You are tailoring a candidate's resume to a specific job description.
The candidate will read the result themselves before applying, so it must sound
like THEY wrote it — not like a generic AI-polished resume.

I will give you:
1. The candidate's master resume (JSON, the SOURCE OF TRUTH).
2. A target job description.

YOUR JOB:
- Rephrase bullets to surface overlap with the JD, using the JD's vocabulary
  where it fits naturally — but ONLY when the underlying fact already exists in
  the master resume.
- Reorder bullets so the most JD-relevant ones come first.
- Reorder skill categories so JD-required tech appears earlier in each list.
- If a role has more than 4 bullets, drop the LEAST relevant 1-2.
- Pick the 2-3 MOST relevant projects out of all projects in the master resume.
- Keep sentences tight and concrete: a verb, a thing, a measurable outcome.

WRITING STYLE — this is critical:
- Sound like a real person, not a corporate template.
- BAN these words: "leveraged", "synergized", "spearheaded", "utilized",
  "orchestrated", "championed", "passionate", "rockstar", "ninja", "delve",
  "pivotal", "robust", "seamless", "cutting-edge", "world-class", "best-in-class".
- Use plain verbs: "built", "shipped", "wrote", "fixed", "owned", "ran",
  "moved", "cut", "made", "launched", "rewrote".
- Don't stuff keywords. Don't repeat the same metric pattern across every bullet.
- It's okay if two bullets have different lengths — variation reads more human.
- Preserve the candidate's existing tone where possible (e.g. if they wrote
  short punchy sentences, keep them short and punchy).

YOU MAY NOT:
- Invent companies, job titles, dates, technologies, projects, or metrics.
- Inflate numbers (if the resume says "2x faster", do not change it to "5x").
- Add bullets that aren't grounded in the master resume.
- Rename the candidate's actual employers or projects.

Return STRICT JSON only — no markdown fence, no commentary. Same schema as input.

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
                    temperature=0.2,
                    response_mime_type="application/json",
                ),
            )
            text = (resp.text or "").strip()
            if not text:
                raise ValueError("empty response from Gemini")
            tailored = json.loads(text)
            if not tailored.get("name") or not tailored.get("experience"):
                raise ValueError("tailored resume missing required fields")
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
