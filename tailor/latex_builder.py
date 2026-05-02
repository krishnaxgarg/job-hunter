"""Render a tailored resume dict into Jake's LaTeX template, then compile to PDF.

LaTeX compilation is done via the `pdflatex` binary, which is installed in the
GitHub Actions runner via the `xu-cheng/latex-action` step. Locally, you need
TeX Live (`brew install --cask mactex-no-gui` or `apt install texlive-full`).
"""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

TEMPLATE = Path("resume/jakes_resume_template.tex")


# ─── LaTeX-safe escaping ─────────────────────────────────────────────────────


_LATEX_REPLACEMENTS = {
    "&": r"\&", "%": r"\%", "$": r"\$", "#": r"\#",
    "_": r"\_", "{": r"\{", "}": r"\}",
    "~": r"\textasciitilde{}", "^": r"\textasciicircum{}",
    "\\": r"\textbackslash{}",
}


def esc(s: str) -> str:
    if s is None:
        return ""
    out = []
    for ch in str(s):
        out.append(_LATEX_REPLACEMENTS.get(ch, ch))
    return "".join(out)


# ─── Block builders ──────────────────────────────────────────────────────────


def _education_block(education: list[dict]) -> str:
    lines: list[str] = []
    for ed in education:
        lines.append(
            "    \\resumeSubheading\n"
            f"      {{{esc(ed.get('school',''))}}}{{{esc(ed.get('location',''))}}}\n"
            f"      {{{esc(ed.get('degree',''))}}}{{{esc(ed.get('dates',''))}}}"
        )
    return "\n".join(lines)


def _experience_block(experience: list[dict]) -> str:
    parts: list[str] = []
    for exp in experience:
        parts.append(
            "    \\resumeSubheading\n"
            f"      {{{esc(exp.get('title',''))}}}{{{esc(exp.get('dates',''))}}}\n"
            f"      {{{esc(exp.get('company',''))}}}{{{esc(exp.get('location',''))}}}\n"
            "      \\resumeItemListStart"
        )
        for b in exp.get("bullets", []):
            parts.append(f"        \\resumeItem{{{esc(b)}}}")
        parts.append("      \\resumeItemListEnd")
    return "\n".join(parts)


def _projects_block(projects: list[dict]) -> str:
    parts: list[str] = []
    for p in projects:
        tech_str = ", ".join(p.get("tech", []))
        parts.append(
            "      \\resumeProjectHeading\n"
            f"          {{\\textbf{{{esc(p.get('name',''))}}} $|$ \\emph{{{esc(tech_str)}}}}}{{{esc(p.get('dates',''))}}}\n"
            "          \\resumeItemListStart"
        )
        for b in p.get("bullets", []):
            parts.append(f"            \\resumeItem{{{esc(b)}}}")
        parts.append("          \\resumeItemListEnd")
    return "\n".join(parts)


def _skills_block(skills: dict) -> str:
    rows = [
        ("Languages", skills.get("languages", [])),
        ("Frameworks", skills.get("frameworks", [])),
        ("Databases", skills.get("databases", [])),
        ("Cloud / DevOps", skills.get("cloud_devops", [])),
        ("Other", skills.get("other", [])),
    ]
    parts: list[str] = []
    for label, vals in rows:
        if not vals:
            continue
        parts.append(f"     \\textbf{{{esc(label)}}}{{: {esc(', '.join(vals))}}} \\\\")
    return "\n".join(parts)


# ─── Render ──────────────────────────────────────────────────────────────────


def render_tex(tailored: dict) -> str:
    tex = TEMPLATE.read_text()

    replacements = {
        "{{NAME}}": esc(tailored.get("name", "")),
        "{{PHONE}}": esc(tailored.get("phone", "")),
        "{{EMAIL}}": esc(tailored.get("email", "")),
        "{{LINKEDIN}}": esc(tailored.get("linkedin", "")),
        "{{GITHUB}}": esc(tailored.get("github", "")),
        "{{EDUCATION_BLOCK}}": _education_block(tailored.get("education", [])),
        "{{EXPERIENCE_BLOCK}}": _experience_block(tailored.get("experience", [])),
        "{{PROJECTS_BLOCK}}": _projects_block(tailored.get("projects", [])),
        "{{SKILLS_BLOCK}}": _skills_block(tailored.get("skills", {})),
    }
    for k, v in replacements.items():
        tex = tex.replace(k, v)
    return tex


def compile_pdf(tex_source: str, out_dir: Path, basename: str) -> Path | None:
    """Compile tex to PDF. Returns path to PDF or None on failure."""
    out_dir.mkdir(parents=True, exist_ok=True)
    tex_file = out_dir / f"{basename}.tex"
    tex_file.write_text(tex_source)

    if not shutil.which("pdflatex"):
        logger.error("pdflatex not on PATH — install TeX Live or rely on GH Action runner")
        return None

    for _ in range(2):  # 2 passes for refs
        result = subprocess.run(
            ["pdflatex", "-interaction=nonstopmode", "-output-directory", str(out_dir),
             str(tex_file)],
            capture_output=True, text=True, timeout=60,
        )
        if result.returncode != 0:
            log_tail = (result.stdout or "")[-1500:]
            logger.error("pdflatex failed:\n%s", log_tail)
            return None

    pdf = out_dir / f"{basename}.pdf"
    return pdf if pdf.exists() else None


def build_for_job(tailored_resume: dict, job_id: str, out_dir: Path = Path("db/pdfs")) -> Path | None:
    tex = render_tex(tailored_resume)
    safe_name = re.sub(r"[^a-z0-9]+", "_", job_id.lower())[:40] or "resume"
    return compile_pdf(tex, out_dir, safe_name)
