from playwright.sync_api import Browser, Locator, Page, expect


def join(page: Page, name: str) -> None:
    page.goto("/")
    form = page.locator("#player-form")
    form.locator("input[name=name]").fill(name)
    form.locator("button[type=submit]").click()
    expect(form).to_have_count(0)


def place_brick(page: Page) -> Locator:
    cell = page.locator(".grid-cell:not(:has(.brick))").first
    cell_id = cell.get_attribute("id")
    cell.locator(":scope > button").click()
    cell = page.locator(f"#{cell_id}")
    expect(cell.locator(".brick")).to_have_count(1)
    return cell


def center(locator: Locator) -> tuple[float, float]:
    box = locator.bounding_box()
    return box["x"] + box["width"] / 2, box["y"] + box["height"] / 2


def test_desktop_drag_moves_brick(joined_page: Page):
    page = joined_page
    source = place_brick(page)
    target = page.locator(".grid-cell:not(:has(.brick))").first
    target = page.locator(f"#{target.get_attribute('id')}")
    brick_id = source.locator(".brick").get_attribute("id")

    page.mouse.move(
        *center(source.locator(".brick > button:not([hx-delete]):not([hidden])"))
    )
    page.mouse.down()
    page.mouse.move(*center(target.locator(":scope > button")), steps=8)
    assert target.evaluate("element => element.matches(':hover')")
    page.mouse.up()

    expect(target.locator(f"#{brick_id}")).to_have_count(1)
    expect(target.locator(".brick")).to_have_count(1)
    expect(source.locator(f"#{brick_id}")).to_have_count(0)


def test_release_waits_for_final_cursor(joined_page: Page):
    page = joined_page
    source = place_brick(page)
    target = page.locator(".grid-cell:not(:has(.brick))").first
    target = page.locator(f"#{target.get_attribute('id')}")
    brick_id = source.locator(".brick").get_attribute("id")

    with page.expect_response("**/grab"):
        page.locator(f"#{brick_id}").dispatch_event("dragstart")
    expect(page.locator(f"#{brick_id}")).to_have_attribute("data-dragging", "")

    held_cursor = []
    requests = []
    page.on("request", lambda request: requests.append(request.url))
    page.route("**/cursor", lambda route: held_cursor.append(route))

    target.dispatch_event("pointerenter")
    page.wait_for_timeout(50)
    assert len(held_cursor) == 1

    page.locator(f"#{brick_id}").dispatch_event("dragend")
    page.wait_for_timeout(100)
    assert not any(url.endswith("/release") for url in requests)

    held_cursor[0].continue_()
    expect(target.locator(f"#{brick_id}")).to_have_count(1)
    expect(source.locator(f"#{brick_id}")).to_have_count(0)


def test_touch_drag_moves_brick(browser: Browser, browser_errors):
    context = browser.new_context(
        base_url="http://fastapi:8000",
        has_touch=True,
        is_mobile=True,
        viewport={"width": 390, "height": 844},
    )
    page = context.new_page()
    browser_errors(page)
    join(page, "Touch Drag")
    source = place_brick(page)
    target = page.locator(".grid-cell:not(:has(.brick))").first
    target = page.locator(f"#{target.get_attribute('id')}")
    brick_id = source.locator(".brick").get_attribute("id")
    page.evaluate(
        """() => {
            window.dragEvents = []
            document.addEventListener('dragstart', () => dragEvents.push('dragstart'))
            document.addEventListener('dragend', () => dragEvents.push('dragend'))
        }"""
    )
    source_x, source_y = center(
        source.locator(".brick > button:not([hx-delete]):not([hidden])")
    )
    target_x, target_y = center(target.locator(":scope > button"))
    cdp = context.new_cdp_session(page)

    cdp.send(
        "Input.dispatchTouchEvent",
        {
            "type": "touchStart",
            "touchPoints": [{"x": source_x, "y": source_y, "id": 1}],
        },
    )
    page.wait_for_timeout(20)
    for step in range(1, 9):
        cdp.send(
            "Input.dispatchTouchEvent",
            {
                "type": "touchMove",
                "touchPoints": [
                    {
                        "x": source_x + (target_x - source_x) * step / 8,
                        "y": source_y + (target_y - source_y) * step / 8,
                        "id": 1,
                    }
                ],
            },
        )
        page.wait_for_timeout(20)
    cdp.send("Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []})

    assert page.evaluate("dragEvents") == ["dragstart", "dragend"]
    expect(target.locator(f"#{brick_id}")).to_have_count(1)
    expect(source.locator(f"#{brick_id}")).to_have_count(0)
    context.close()


def test_control_menus_are_mutually_exclusive(page: Page, browser_errors):
    browser_errors(page)
    join(page, "scriptogre")
    admin = page.locator("#admin")
    players = page.locator("#players")
    settings = page.locator("#settings")

    players.locator("summary").click()
    expect(players).to_have_attribute("open", "")

    admin.locator("summary").click()
    expect(admin).to_have_attribute("open", "")
    expect(players).not_to_have_attribute("open", "")

    settings.locator("summary").click()
    expect(settings).to_have_attribute("open", "")
    expect(admin).not_to_have_attribute("open", "")

    players.locator("summary").click()
    expect(players).to_have_attribute("open", "")
    expect(settings).not_to_have_attribute("open", "")


def test_prediction_toggle_controls_delete(joined_page: Page):
    page = joined_page
    predicted_cell = place_brick(page)
    unpredicted_cell = place_brick(page)
    settings = page.locator("#settings")
    toggle = page.locator("#predictions-toggle")

    def fake_delete(route):
        if route.request.method == "DELETE":
            route.fulfill(status=204)
        else:
            route.continue_()

    page.route("**/bricks/*", fake_delete)

    expect(toggle).to_be_checked()
    expect(settings).not_to_have_attribute("open", "")
    settings.locator("summary").click()
    expect(settings).to_have_attribute("open", "")
    page.locator("#simulate-latency-toggle").check()

    predicted_cell.locator("button[hx-delete]").dispatch_event("pointerdown")
    expect(predicted_cell.locator(".brick")).to_have_count(0, timeout=100)

    toggle.uncheck()
    expect(toggle).not_to_be_checked()
    unpredicted_cell.locator("button[hx-delete]").dispatch_event("pointerdown")
    page.wait_for_timeout(600)
    expect(unpredicted_cell.locator(".brick")).to_have_count(1)


def test_touch_delete_mode_deletes_brick(browser: Browser, browser_errors):
    context = browser.new_context(
        base_url="http://fastapi:8000",
        has_touch=True,
        is_mobile=True,
        viewport={"width": 390, "height": 844},
    )
    page = context.new_page()
    browser_errors(page)
    join(page, "Touch Delete")
    expect(page.locator("#controls")).to_be_visible()
    cell = place_brick(page)
    brick = cell.locator(".brick")
    delete_button = brick.locator("button[hx-delete]")
    mode_button = page.locator("#delete-mode-button")

    expect(mode_button).to_be_visible()
    expect(mode_button).to_have_attribute("aria-pressed", "false")
    expect(delete_button).not_to_be_visible()

    mode_button.tap()

    expect(page.locator("body")).to_have_attribute("data-delete-mode", "true")
    expect(mode_button).to_have_attribute("aria-pressed", "true")
    expect(mode_button).to_contain_text("Delete")
    expect(mode_button.locator(".icon-\\[lucide--check\\]")).to_be_visible()
    expect(mode_button.locator(".icon-\\[lucide--trash-2\\]")).not_to_be_visible()
    expect(brick).to_have_attribute("draggable", "false")
    expect(delete_button).to_be_visible()

    delete_button.tap()

    expect(cell.locator(".brick")).to_have_count(0)
    context.close()


def test_shift_drag_deletes_touched_bricks(joined_page: Page):
    page = joined_page
    cells = [place_brick(page) for _ in range(3)]

    page.keyboard.down("Shift")
    expect(page.locator("body")).to_have_attribute("data-delete-mode", "true")
    page.mouse.move(*center(cells[0].locator(".brick > button[hx-delete]")))
    page.mouse.down()
    for cell in cells[1:]:
        page.mouse.move(*center(cell.locator(".brick > button[hx-delete]")), steps=8)
    page.mouse.up()
    page.keyboard.up("Shift")
    expect(page.locator("body")).to_have_attribute("data-delete-mode", "false")

    for cell in cells:
        expect(cell.locator(".brick")).to_have_count(0)
