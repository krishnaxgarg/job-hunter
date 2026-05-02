"""Best-effort auto-apply helper for ATS pages (Greenhouse, Lever, Ashby).

This is invoked by GitHub Actions on demand (when the user has tapped Apply
on Telegram and the job's ats field is one of the supported ones).

Uses Playwright in headless Chromium to:
- open the job's apply URL
- fill name / email / phone / linkedin / github
- upload the tailored resume PDF
- click submit (ONLY if the user has set AUTO_SUBMIT=true in repo secrets)

Otherwise it stops at the pre-filled form and screenshots it so the user can
take over from a browser.

NB: this is intentionally limited to Greenhouse/Lever/Ashby — those have stable
form structures. LinkedIn / Naukri / company custom forms are NOT supported
because they break constantly and risk account bans.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

MASTER = json.loads(Path("resume/master_resume.json").read_text())
AUTO_SUBMIT = os.environ.get("AUTO_SUBMIT", "false").lower() == "true"


async def _apply_greenhouse(page, pdf_path: Path) -> bool:
    await page.fill('input[name="job_application[first_name]"]',
                    MASTER["name"].split()[0])
    await page.fill('input[name="job_application[last_name]"]',
                    " ".join(MASTER["name"].split()[1:]) or MASTER["name"])
    await page.fill('input[name="job_application[email]"]', MASTER["email"])
    if await page.locator('input[name="job_application[phone]"]').count():
        await page.fill('input[name="job_application[phone]"]', MASTER["phone"])
    # resume upload
    file_input = page.locator('input[type="file"]').first
    await file_input.set_input_files(str(pdf_path))
    await page.wait_for_timeout(2000)
    if AUTO_SUBMIT:
        await page.click('input[type="submit"]')
    return True


async def _apply_lever(page, pdf_path: Path) -> bool:
    await page.fill('input[name="name"]', MASTER["name"])
    await page.fill('input[name="email"]', MASTER["email"])
    if await page.locator('input[name="phone"]').count():
        await page.fill('input[name="phone"]', MASTER["phone"])
    if await page.locator('input[name="urls[LinkedIn]"]').count():
        await page.fill('input[name="urls[LinkedIn]"]', f"https://{MASTER['linkedin']}")
    if await page.locator('input[name="urls[GitHub]"]').count():
        await page.fill('input[name="urls[GitHub]"]', f"https://{MASTER['github']}")
    file_input = page.locator('input[type="file"]').first
    await file_input.set_input_files(str(pdf_path))
    await page.wait_for_timeout(2000)
    if AUTO_SUBMIT:
        await page.click('button[type="submit"]')
    return True


async def _apply_ashby(page, pdf_path: Path) -> bool:
    # Ashby uses generic input names — best-effort
    name_input = page.locator('input[id*="name" i]').first
    if await name_input.count():
        await name_input.fill(MASTER["name"])
    email_input = page.locator('input[type="email"]').first
    if await email_input.count():
        await email_input.fill(MASTER["email"])
    file_input = page.locator('input[type="file"]').first
    await file_input.set_input_files(str(pdf_path))
    await page.wait_for_timeout(2000)
    if AUTO_SUBMIT:
        submit = page.locator('button[type="submit"]').first
        if await submit.count():
            await submit.click()
    return True


_DISPATCH = {
    "greenhouse": _apply_greenhouse,
    "lever": _apply_lever,
    "ashby": _apply_ashby,
}


async def apply(url: str, ats: str, pdf_path: Path, screenshot_path: Path) -> dict:
    if ats not in _DISPATCH:
        return {"ok": False, "reason": f"unsupported ATS: {ats}"}
    if not pdf_path.exists():
        return {"ok": False, "reason": "PDF missing"}

    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context()
        page = await ctx.new_page()
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await _DISPATCH[ats](page, pdf_path)
            await page.screenshot(path=str(screenshot_path), full_page=True)
            return {"ok": True, "submitted": AUTO_SUBMIT}
        except Exception as e:    # noqa: BLE001
            try:
                await page.screenshot(path=str(screenshot_path), full_page=True)
            except Exception:    # noqa: BLE001
                pass
            return {"ok": False, "reason": str(e)}
        finally:
            await browser.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--ats", required=True, choices=list(_DISPATCH.keys()))
    parser.add_argument("--pdf", required=True)
    parser.add_argument("--screenshot", default="db/last_apply.png")
    args = parser.parse_args()

    result = asyncio.run(apply(args.url, args.ats, Path(args.pdf), Path(args.screenshot)))
    print(json.dumps(result))


if __name__ == "__main__":
    main()
