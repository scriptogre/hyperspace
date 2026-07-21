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


def test_drag_from_empty_cell_paints_bricks(joined_page: Page):
    page = joined_page
    cells = []
    for index in range(3):
        cell = page.locator(".grid-cell:not(:has(.brick))").nth(index)
        cells.append(page.locator(f"#{cell.get_attribute('id')}"))

    cells[0].locator(":scope > button").dispatch_event("pointerdown", {"buttons": 1})
    for cell in cells[1:]:
        cell.locator(":scope > button").dispatch_event("pointerenter", {"buttons": 1})

    for cell in cells:
        expect(cell.locator(".brick")).to_have_count(1)


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
    cdp.send("Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []})

    expect(target.locator(f"#{brick_id}")).to_have_count(1)
    expect(source.locator(f"#{brick_id}")).to_have_count(0)
    context.close()


def test_shift_drag_deletes_touched_bricks(joined_page: Page):
    page = joined_page
    cells = [place_brick(page) for _ in range(3)]

    page.keyboard.down("Shift")
    page.mouse.move(*center(cells[0].locator(".brick > button[hx-delete]")))
    page.mouse.down()
    for cell in cells[1:]:
        page.mouse.move(*center(cell.locator(".brick > button[hx-delete]")), steps=8)
    page.mouse.up()
    page.keyboard.up("Shift")

    for cell in cells:
        expect(cell.locator(".brick")).to_have_count(0)
