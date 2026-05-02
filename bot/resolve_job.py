"""Look up a job row by ID and emit GH-Actions step outputs.

Used by .github/workflows/apply.yml — the Cloudflare Worker only sends a
short job_id, so we resolve url / ats / pdf_path here from jobs.db.
"""

from __future__ import annotations

import argparse
import glob
import os
import re
import sqlite3
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--id", required=True)
    parser.add_argument("--out", default=os.environ.get("GITHUB_OUTPUT", "/dev/stdout"))
    args = parser.parse_args()

    db_path = Path(os.environ.get("JOB_DB_PATH", "db/jobs.db"))
    if not db_path.exists():
        print("DB not found", file=sys.stderr)
        return 1

    with sqlite3.connect(db_path) as c:
        row = c.execute(
            "SELECT url, ats, company FROM jobs WHERE id = ?", (args.id,)
        ).fetchone()
    if not row:
        print(f"job {args.id} not found in DB", file=sys.stderr)
        return 2

    url, ats, company = row
    if not ats:
        print(f"job {args.id} has no ATS — auto-apply unsupported", file=sys.stderr)
        # still write outputs so the workflow can short-circuit cleanly
        ats = ""

    # The PDF was generated during send_jobs as <Name>_<Company>.pdf.
    # We don't have the exact name here, so safe-substring match by listing.
    pdf_dir = Path("db/pdfs")
    needle = re.sub(r"[^A-Za-z0-9]+", "_", company)[:25].lower()
    pdf_path = ""
    if pdf_dir.exists():
        candidates = [
            p for p in pdf_dir.iterdir()
            if p.suffix == ".pdf" and needle and needle in re.sub(
                r"[^A-Za-z0-9]+", "_", p.stem).lower()
        ]
        candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        if candidates:
            pdf_path = str(candidates[0])

    # Emit step outputs
    with open(args.out, "a") as f:
        f.write(f"url={url}\n")
        f.write(f"ats={ats}\n")
        f.write(f"pdf_path={pdf_path}\n")
    print(f"resolved: url={url} ats={ats} pdf={pdf_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
