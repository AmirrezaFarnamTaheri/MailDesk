"""Run MailDesk's browser visual-review smoke journey with Playwright.

The target service must already be running.  CI uses this script to capture the
real Senders surface after confirming the critical first-run journey works.
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import async_playwright, expect


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the MailDesk visual-review E2E journey.")
    parser.add_argument("--url", default="http://127.0.0.1:8765", help="Running MailDesk URL.")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/visual-review/senders.png"),
        help="PNG review artifact path.",
    )
    return parser.parse_args()


async def wait_for_application(page, url: str) -> None:
    for _ in range(30):
        try:
            response = await page.goto(url, wait_until="domcontentloaded", timeout=1_000)
            if response and response.ok:
                return
        except PlaywrightError:
            pass
        await page.wait_for_timeout(250)
    raise RuntimeError(f"MailDesk did not become available at {url}.")


async def review(args: argparse.Namespace) -> Path:
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        page = await browser.new_page(viewport={"width": 1440, "height": 1000}, device_scale_factor=1)
        try:
            # Keep the review focused on the stable product surface; tour behavior has
            # dedicated frontend coverage and is not part of this screenshot baseline.
            await page.add_init_script("localStorage.setItem('maildesk-tour-seen-v1', '1')")
            await wait_for_application(page, args.url)
            await expect(page.get_by_test_id("main-content")).to_be_visible()

            await page.get_by_test_id("nav-senders").click()
            await expect(page.get_by_role("heading", name="Senders & settings")).to_be_visible()
            await expect(page.get_by_test_id("gmail-oauth-setup")).to_be_visible()
            await expect(page.get_by_role("heading", name="Gmail accounts")).to_be_visible()
            await expect(page.get_by_role("heading", name="Browser senders")).to_be_visible()
            await page.screenshot(path=str(output), full_page=True)
        finally:
            await browser.close()
    return output


def main() -> None:
    try:
        output = asyncio.run(review(parse_args()))
    except RuntimeError as exc:
        raise SystemExit(str(exc)) from exc
    print(f"Visual review written to {output}")


if __name__ == "__main__":
    main()
