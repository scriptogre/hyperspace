from playwright.sync_api import Page, expect


EVENT_TEXT = "Join us live at BigSkyDevCon 2026"


def test_login_qr_code(page: Page, browser_errors):
    browser_errors(page)
    page.goto("/")

    card = page.locator("#join-qr")
    link = card.locator("a")
    qr_code = link.locator("qr-code")

    expect(card.locator("img")).to_have_attribute(
        "src", "/static/images/logo_transp.png"
    )
    expect(card.locator("p")).to_have_text(EVENT_TEXT)
    expect(link).to_have_attribute("href", page.url.rstrip("/"))
    expect(qr_code).to_have_attribute("content", page.url.rstrip("/"))
    expect(qr_code.locator("svg")).to_be_visible()
