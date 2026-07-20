import re

from playwright.sync_api import Page, expect


def test_color_picker(page: Page):
    page.goto("/")

    form = page.locator("#player-form form")
    suggestions = form.locator(".suggested-color")
    palette = form.locator("details .color-pick")
    color_seed = form.locator("[name=color_seed]")

    expect(suggestions).to_have_count(5)
    expect(palette).to_have_count(100)

    suggestions.nth(1).click()
    expect(color_seed).to_have_value(suggestions.nth(1).get_attribute("data-seed"))

    form.locator("summary").click()
    form.locator('details .color-pick[data-seed="100"]').click()

    expect(color_seed).to_have_value("100")
    expect(form.locator("details")).not_to_have_attribute("open", "")
    expect(form.locator("summary")).to_have_class(re.compile(r"\bhas-color\b"))

    selected_color = form.locator('details [data-seed="100"]').evaluate(
        "element => element.style.getPropertyValue('--base-color').trim()"
    )
    form.locator("input[name=name]").fill("Color Test")
    form.locator("button[type=submit]").click()
    form.wait_for(state="detached")

    empty_cell = page.locator(".grid-cell:not(:has(.brick))").first
    cell = page.locator(f"#{empty_cell.get_attribute('id')}")
    cell.locator(":scope > button").click()

    expect(cell.locator(".brick")).to_have_attribute(
        "style",
        re.compile(rf"--base-color:\s*{re.escape(selected_color)}"),
    )
