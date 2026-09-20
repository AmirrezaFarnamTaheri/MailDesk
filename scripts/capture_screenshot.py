"""Capture a stable MailDesk browser screenshot with Playwright.

Start MailDesk separately, then run this script from the repository root.
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import async_playwright


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Capture a MailDesk Playwright screenshot.")
    parser.add_argument("--url", default="http://127.0.0.1:8765", help="Running MailDesk URL.")
    parser.add_argument("--output", type=Path, default=Path("artifacts/screenshots/maildesk.png"), help="PNG output path.")
    parser.add_argument("--selector", default="#mainContent", help="Element that confirms the page is ready.")
    parser.add_argument("--full-page", action="store_true", help="Capture the complete page instead of the viewport.")
    parser.add_argument("--keep-tour", action="store_true", help="Leave the first-run tour visible in the screenshot.")
    return parser.parse_args()


async def capture(args: argparse.Namespace) -> Path:
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        page = await browser.new_page(viewport={"width": 1440, "height": 1000}, device_scale_factor=1)
        try:
            await page.goto(args.url, wait_until="networkidle")
            await page.locator(args.selector).wait_for(state="visible")
            # The first-run tour is scheduled on the next animation frame.
            await page.wait_for_timeout(250)
            if not args.keep_tour:
                skip_tour = page.locator("#skipTourButton")
                if await skip_tour.is_visible():
                    await skip_tour.click()
                    await page.wait_for_function(
                        "document.querySelector('#tourOverlay')?.classList.contains('is-hidden')"
                    )
                    await page.wait_for_timeout(100)
                # Keep the capture deterministic if the first-run animation starts late.
                await page.add_style_tag(content="#tourOverlay { display: none !important; }")
            await page.screenshot(path=str(output), full_page=args.full_page)
        except PlaywrightError as exc:
            raise RuntimeError(
                f"Could not capture {args.url}. Start MailDesk first and verify the URL."
            ) from exc
        finally:
            await browser.close()
    return output


def main() -> None:
    try:
        output = asyncio.run(capture(parse_args()))
    except RuntimeError as exc:
        raise SystemExit(str(exc)) from exc
    print(f"Screenshot written to {output}")


if __name__ == "__main__":
    main()
