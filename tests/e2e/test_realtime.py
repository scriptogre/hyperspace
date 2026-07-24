import uuid

from playwright.sync_api import Browser, expect


def test_brick_update_reaches_both_players(browser: Browser, browser_errors):
    contexts = [
        browser.new_context(base_url="http://fastapi:8000"),
        browser.new_context(base_url="http://fastapi:8000"),
    ]
    pages = [context.new_page() for context in contexts]

    try:
        for page in pages:
            page.set_default_timeout(10_000)
            browser_errors(page)
            page.goto("/")
            form = page.locator("#player-form")
            form.locator("input[name=name]").fill(f"e2e_{uuid.uuid4().hex[:6]}")
            form.locator("button[type=submit]").click()
            expect(form).to_have_count(0)

        page_a, page_b = pages
        cell = page_a.locator(".grid-cell").evaluate_all(
            """cells => {
                const capacity = Number(getComputedStyle(document.querySelector('#grid'))
                    .getPropertyValue('--world-size'))
                const cell = cells.find(cell =>
                    cell.querySelectorAll(':scope > .brick').length < capacity)
                return {
                    id: cell.id,
                    count: cell.querySelectorAll(':scope > .brick').length,
                }
            }"""
        )
        cell_a = page_a.locator(f"#{cell['id']}")
        cell_b = page_b.locator(f"#{cell['id']}")
        total = page_a.locator(".brick").count()

        expect(page_b.locator(".brick")).to_have_count(total)
        if cell["count"]:
            cell_a.locator(":scope > .brick").last.locator(
                ":scope > button[aria-label='Stack brick']"
            ).click()
        else:
            cell_a.locator(":scope > button[aria-label='Add brick']").click()

        expect(cell_a.locator(":scope > .brick")).to_have_count(cell["count"] + 1)
        expect(cell_b.locator(":scope > .brick")).to_have_count(cell["count"] + 1)
        expect(page_a.locator("#brick-count")).to_have_text(str(total + 1))
        expect(page_b.locator("#brick-count")).to_have_text(str(total + 1))
    finally:
        for context in contexts:
            context.close()
