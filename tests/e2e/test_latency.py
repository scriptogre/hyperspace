import re

from playwright.sync_api import Page, expect


def test_request_latency_display_and_simulator(joined_page: Page):
    page = joined_page
    output = page.get_by_label("Last request time")
    settings = page.locator("#settings")

    expect(output).to_have_text(re.compile(r"\d+ms"))
    settings.locator("summary").click()
    delay = page.locator("#simulate-latency-toggle")
    delay.check()

    timing = page.evaluate(
        """async () => {
            const started = performance.now()
            await htmx.ajax('GET', '/health', {
                source: '#simulate-latency-toggle',
                swap: 'none',
            })
            return {
                elapsed: performance.now() - started,
                rtt: Number(document.querySelector('#request-latency').style.getPropertyValue('--request-latency-ms')),
            }
        }"""
    )

    assert timing["elapsed"] >= 240
    assert timing["elapsed"] - timing["rtt"] >= 200
    expect(output).to_have_text(f"{timing['rtt']}ms")

    for rtt, color in (
        (99, "rgb(34, 195, 34)"),
        (100, "rgb(195, 195, 34)"),
        (250, "rgb(195, 34, 34)"),
    ):
        output.evaluate(
            "(element, value) => element.style.setProperty('--request-latency-ms', value)",
            rtt,
        )
        expect(output).to_have_css("color", color)
