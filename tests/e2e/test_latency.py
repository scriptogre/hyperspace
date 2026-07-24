import re

from playwright.sync_api import Page, expect


def test_request_latency_display_and_simulator(joined_page: Page):
    page = joined_page
    output = page.get_by_label("Last request time")
    delay = page.get_by_label("Added request delay")

    expect(output).to_have_text(re.compile(r"\d+ms"))
    delay.select_option("100")

    timing = page.evaluate(
        """async () => {
            const started = performance.now()
            await htmx.ajax('GET', '/health', {
                source: '#simulated-latency',
                swap: 'none',
            })
            return {
                elapsed: performance.now() - started,
                rtt: Number(document.querySelector('#latency').dataset.rtt),
            }
        }"""
    )

    assert timing["elapsed"] >= 90
    assert timing["elapsed"] - timing["rtt"] >= 80
    expect(output).to_have_text(f"{timing['rtt']}ms")

    for rtt, color in (
        (99, "text-green-600"),
        (100, "text-yellow-600"),
        (250, "text-red-600"),
    ):
        page.locator("#latency").evaluate(
            "(element, value) => element.dataset.rtt = value", rtt
        )
        expect(output).to_have_class(color)
