import re

from playwright.sync_api import Page, expect


def test_color_picker(page: Page, browser_errors):
    browser_errors(page)
    page.goto("/")

    form = page.locator("#player-form")
    suggestions = form.locator("#color-options > label")
    palette = form.locator("#color-menu > label")

    expect(suggestions).to_have_count(5)
    expect(palette).to_have_count(100)

    suggestions.nth(1).click()
    expect(suggestions.nth(1).locator("input")).to_be_checked()

    form.locator("summary").click()
    selected_option = form.locator('#color-menu label:has(input[value="100"])')
    selected_option.click()

    expect(selected_option.locator("input")).to_be_checked()
    expect(form.locator("details")).not_to_have_attribute("open", "")

    selected_color = selected_option.evaluate(
        "element => element.style.getPropertyValue('--color').trim()"
    )
    form.locator("input[name=name]").fill("Color Test")
    form.locator("button[type=submit]").click()
    form.wait_for(state="detached")

    empty_cell = page.locator("[id^=grid-cell-]:not(:has([id^=brick-]))").first
    cell = page.locator(f"#{empty_cell.get_attribute('id')}")
    cell.locator(":scope > button").click()

    expect(cell.locator("[id^=brick-]")).to_have_attribute(
        "style",
        re.compile(rf"--color:\s*{re.escape(selected_color)}"),
    )
