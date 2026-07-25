import uuid

from playwright.sync_api import BrowserType, expect


def test_stream_uses_native_zstd(browser_type: BrowserType, browser_errors):
    browser = browser_type.launch(args=["--host-resolver-rules=MAP localhost fastapi"])
    context = browser.new_context(base_url="http://localhost:8000")
    page = context.new_page()

    try:
        page.set_default_timeout(10_000)
        browser_errors(page)
        with page.expect_response("**/stream") as stream_response:
            page.goto("/")

        assert stream_response.value.headers["content-encoding"] == "zstd"

        form = page.locator("#player-form")
        form.locator("input[name=name]").fill(f"zstd_{uuid.uuid4().hex[:6]}")
        form.locator("button[type=submit]").click()
        expect(form).to_have_count(0)

        cell = page.locator("[id^=grid-cell-]").evaluate_all(
            """cells => cells.find(cell => !cell.querySelector(':scope > [id^=brick-]')).id"""
        )
        placed = page.locator(f"#{cell} > [id^=brick-]")
        page.locator(f"#{cell} > button").click()
        expect(placed).to_have_count(1)
    finally:
        context.close()
        browser.close()
