"""Capture a broad, deterministic Playwright visual review of the local app.

The target service must already be running. The journey uses the real loopback
API for worksheet/render state and mocks only the external Google consent page.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import async_playwright, expect


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the MailDesk visual-review E2E journey.")
    parser.add_argument("--url", default="http://127.0.0.1:8765", help="Running MailDesk URL.")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/visual-review/accounts.png"),
        help="Accounts screenshot path; sibling workflow screenshots are written beside it.",
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


async def review(args: argparse.Namespace) -> list[Path]:
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    names = {
        "worksheet": "compose-worksheet.png",
        "write": "write.png",
        "preview": "preview.png",
        "send": "send.png",
        "campaigns": "campaigns.png",
        "activity": "activity.png",
        "accounts": output.name,
        "oauth": "oauth-popup.png",
    }
    captures = [output.with_name(name) for name in names.values()]
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        context = await browser.new_context(viewport={"width": 1440, "height": 1000}, device_scale_factor=1)

        async def mock_external_google(route):
            await route.fulfill(
                status=200,
                content_type="text/html",
                body="<main style='font:16px system-ui;padding:48px'><h1>Google sign-in</h1><p>Mock consent window for visual review.</p><button>Continue</button></main>",
            )

        async def mock_oauth_start(route):
            await route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({"auth_url": f"{args.url}/oauth/mock-consent"}),
            )

        await context.route("**/oauth/mock-consent", mock_external_google)
        await context.route("**/api/accounts/google/start", mock_oauth_start)
        page = await context.new_page()
        try:
            await page.add_init_script("localStorage.setItem('maildesk-tour-seen-v1', '1')")
            await wait_for_application(page, args.url)
            await expect(page.get_by_test_id("main-content")).to_be_visible()
            worksheet = page.get_by_role("region", name="Built-in worksheet")
            await expect(worksheet).to_be_visible()
            await expect(page.get_by_role("table", name="Built-in recipient worksheet")).to_be_visible()
            await page.screenshot(path=str(output.with_name(names["worksheet"])), full_page=True)

            await page.get_by_role("textbox", name="Email, row 1").fill("ada@example.com")
            await page.get_by_role("textbox", name="Name, row 1").fill("Ada")
            await page.get_by_role("button", name="Use worksheet").click()
            email_column = page.get_by_role("combobox", name="Recipient email")
            await page.locator("#recipientMappingDetails").get_by_text("Edit column mapping").click()
            await email_column.select_option("Email")
            await page.get_by_role("button", name="Continue to write").click()
            await expect(page.get_by_role("heading", name="Write")).to_be_visible()
            await page.screenshot(path=str(output.with_name(names["write"])), full_page=True)

            await page.get_by_role("textbox", name="Subject").fill("Hello {{Name}}")
            await page.get_by_role("textbox", name="Message").fill("Welcome, {{Name}}.")
            await page.get_by_role("button", name="Preview messages").click()
            await expect(page.get_by_role("heading", name="Preview")).to_be_visible()
            await page.screenshot(path=str(output.with_name(names["preview"])), full_page=True)

            await page.get_by_role("button", name="Continue to send").click()
            await expect(page.get_by_role("heading", name="Send")).to_be_visible()
            await page.screenshot(path=str(output.with_name(names["send"])), full_page=True)

            await page.get_by_role("button", name="Campaigns").click()
            await expect(page.locator("#queueView").get_by_role("heading", name="Campaigns")).to_be_visible()
            await page.screenshot(path=str(output.with_name(names["campaigns"])), full_page=True)

            await page.get_by_role("button", name="Activity").click()
            await expect(page.locator("#historyView").get_by_role("heading", name="Activity")).to_be_visible()
            await page.screenshot(path=str(output.with_name(names["activity"])), full_page=True)

            await page.get_by_test_id("nav-accounts").click()
            await expect(page.locator("#viewTitle")).to_have_text("Accounts & settings")
            await expect(page.get_by_test_id("gmail-oauth-setup")).to_be_visible()
            await expect(page.get_by_role("heading", name="Gmail accounts")).to_be_visible()
            await expect(page.get_by_role("heading", name="Browser accounts")).to_be_visible()
            await page.locator("#connectGoogleButton").evaluate("button => { button.disabled = false; }")
            async with page.expect_popup() as popup_info:
                await page.get_by_role("button", name="Connect Gmail").click()
            popup = await popup_info.value
            await expect(popup.get_by_role("heading", name="Google sign-in")).to_be_visible()
            await popup.screenshot(path=str(output.with_name(names["oauth"])), full_page=True)
            await page.screenshot(path=str(output), full_page=True)
        finally:
            await context.close()
            await browser.close()
    return captures


def main() -> None:
    try:
        captures = asyncio.run(review(parse_args()))
    except RuntimeError as exc:
        raise SystemExit(str(exc)) from exc
    print("Visual reviews written:")
    for capture in captures:
        print(capture)


if __name__ == "__main__":
    main()
