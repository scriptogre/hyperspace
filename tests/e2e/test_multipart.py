from playwright.sync_api import Page, expect


def multipart(content: str, headers: tuple[str, ...] = (), closed: bool = True) -> str:
    lines = [
        "--test",
        "Content-Type: text/html",
        f"Content-Length: {len(content.encode())}",
        *headers,
        "",
        content,
    ]
    if closed:
        lines.extend(("--test--", ""))
    return "\r\n".join(lines)


def test_multipart_swap_precedence(page: Page):
    content = "".join(
        (
            '<span class="request-choice">request</span>',
            '<span class="envelope-choice">envelope</span>',
            '<span class="part-choice">part</span>',
            '<span class="re-choice">re</span>',
        )
    )
    accept_headers = []

    def fulfill(route, *, envelope=(), part=()):
        accept_headers.append(route.request.headers["accept"])
        route.fulfill(
            body=multipart(content, part),
            headers={
                "Content-Type": "multipart/mixed; boundary=test",
                **dict(envelope),
            },
        )

    page.route("**/request-defaults", lambda route: fulfill(route))
    page.route(
        "**/envelope-defaults",
        lambda route: fulfill(
            route,
            envelope=(
                ("HX-Retarget", "#envelope-target"),
                ("HX-Reswap", "innerHTML"),
                ("HX-Reselect", ".envelope-choice"),
            ),
        ),
    )
    page.route(
        "**/part-direct",
        lambda route: fulfill(
            route,
            envelope=(
                ("HX-Retarget", "#envelope-target"),
                ("HX-Reswap", "beforeend"),
                ("HX-Reselect", ".envelope-choice"),
            ),
            part=(
                "HX-Target: #part-target",
                "HX-Swap: innerHTML",
                "HX-Select: .part-choice",
            ),
        ),
    )
    page.route(
        "**/part-re",
        lambda route: fulfill(
            route,
            part=(
                "HX-Target: #part-target",
                "HX-Swap: innerHTML",
                "HX-Select: .part-choice",
                "HX-Retarget: #re-target",
                "HX-Reswap: beforeend",
                "HX-Reselect: .re-choice",
            ),
        ),
    )

    page.goto("/")
    page.evaluate(
        """() => {
            document.body.insertAdjacentHTML('beforeend', `
                <button id="request" hx-get="/request-defaults"
                        hx-target="#request-target" hx-swap="innerHTML"
                        hx-select=".request-choice">request</button>
                <button id="envelope" hx-get="/envelope-defaults"
                        hx-target="#request-target">envelope</button>
                <button id="part" hx-get="/part-direct">part</button>
                <button id="re" hx-get="/part-re">re</button>
                <div id="request-target">existing</div>
                <div id="envelope-target">existing</div>
                <div id="part-target">existing</div>
                <div id="re-target">existing</div>
            `)
            htmx.process(document.body)
        }"""
    )

    page.locator("#request").click()
    expect(page.locator("#request-target")).to_have_text("request")

    page.locator("#envelope").click()
    expect(page.locator("#envelope-target")).to_have_text("envelope")

    page.locator("#part").click()
    expect(page.locator("#part-target")).to_have_text("part")

    page.locator("#re").click()
    expect(page.locator("#re-target")).to_have_text("existingre")

    assert accept_headers == ["text/html, multipart/mixed, multipart/parallel"] * 4


def test_multipart_connect_reconnects_after_clean_end_and_stops_on_removal(page: Page):
    requests = 0

    def fulfill(route):
        nonlocal requests
        requests += 1
        route.fulfill(
            body=multipart(
                f'<span id="connection-count">{requests}</span>',
                (
                    "HX-Target: #connection-target",
                    "HX-Swap: innerHTML",
                ),
            ),
            headers={"Content-Type": "multipart/mixed; boundary=test"},
        )

    page.route("**/clean-stream", fulfill)
    page.goto("/")
    page.evaluate(
        """() => {
            document.body.insertAdjacentHTML('beforeend', `
                <div id="source" hx-multipart:connect="/clean-stream"></div>
                <div id="connection-target"></div>
            `)
            htmx.process(document.querySelector('#source'))
        }"""
    )

    expect(page.locator("#connection-count")).to_have_text("2", timeout=5_000)

    page.evaluate("htmx.swap('', '#source', {style: 'delete'})")
    stopped_at = requests
    page.wait_for_timeout(1_500)
    assert requests == stopped_at


def test_multipart_connect_reconnects_after_broken_stream(page: Page):
    requests = 0

    def fulfill(route):
        nonlocal requests
        requests += 1
        route.fulfill(
            body=multipart(
                f'<span id="broken-count">{requests}</span>',
                (
                    "HX-Target: #broken-target",
                    "HX-Swap: innerHTML",
                ),
                closed=requests > 1,
            ),
            headers={"Content-Type": "multipart/mixed; boundary=test"},
        )

    page.route("**/broken-stream", fulfill)
    page.goto("/")
    page.evaluate(
        """() => {
            document.body.insertAdjacentHTML('beforeend', `
                <div id="source" hx-multipart:connect="/broken-stream"></div>
                <div id="broken-target"></div>
            `)
            htmx.process(document.querySelector('#source'))
        }"""
    )

    page.wait_for_function(
        "Number(document.querySelector('#broken-count')?.textContent) >= 2",
        timeout=5_000,
    )
    assert requests >= 2
