import { test, expect, Page } from '@playwright/test';

/** Connect, wait for the WS-driven welcome modal, then complete setup. */
async function join(page: Page, name = 'Player') {
  await page.waitForFunction(() => localStorage.getItem('stdb_token') !== null, { timeout: 10_000 });
  await expect(page.locator('#welcome-modal')).toBeVisible({ timeout: 10_000 });
  await page.fill('input[name="set_name"]', name);
  await page.locator('.color-pick').first().click();
  await page.locator('button[name="continue"]').click();
  // Setup complete: server logs "joined", broadcast morphs the modal away.
  await expect(page.locator('#welcome-modal')).toHaveCount(0, { timeout: 8_000 });
}

/** Click a grid cell at the given coordinates. */
async function clickCell(page: Page, x: number, y: number) {
  const cell = page.locator(`button[data-cell-x="${x}"][data-cell-y="${y}"]`);
  await cell.click({ force: true });
}

/** A brick at a grid cell (bricks carry data-x / data-y, not data-cell-*). */
function brickAt(page: Page, x: number, y: number) {
  return page.locator(`[data-brick-id][data-x="${x}"][data-y="${y}"]`);
}

test.describe('page load', () => {
  test('serves HTML with grid and welcome modal', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('#grid-viewport')).toBeVisible();
    // The modal arrives via the initial WS subscription morph.
    await expect(page.locator('#welcome-modal')).toBeVisible({ timeout: 10_000 });
    await expect(page.locator('input[name="set_name"]')).toBeVisible();
  });

  test('no JS errors on load', async ({ page }) => {
    const errors: string[] = [];
    page.on('pageerror', (err) => errors.push(err.message));
    await page.goto('/');
    await page.waitForTimeout(3000);
    expect(errors).toEqual([]);
  });
});

test.describe('websocket connection', () => {
  test('connects and stores token', async ({ page }) => {
    await page.goto('/');
    await page.waitForFunction(
      () => localStorage.getItem('stdb_token') !== null,
      { timeout: 10_000 },
    );
    const token = await page.evaluate(() => localStorage.getItem('stdb_token'));
    expect(token).toBeTruthy();
    expect(token!.length).toBeGreaterThan(10);
  });

  test('completing setup logs a join event', async ({ page }) => {
    await page.goto('/');
    await join(page, 'Joiner');
    await expect(page.locator('#console-log')).toContainText('joined', { timeout: 8_000 });
  });
});

test.describe('reducer calls', () => {
  test('clicking a grid cell creates a brick', async ({ page }) => {
    await page.goto('/');
    await join(page);

    const x = 10, y = 0;
    const before = await brickAt(page, x, y).count();
    await clickCell(page, x, y);
    if (before < 5) {
      await expect(brickAt(page, x, y)).toHaveCount(before + 1, { timeout: 8000 });
    }
  });

  test('shift+clicking a brick deletes it', async ({ page }) => {
    await page.goto('/');
    await join(page);

    // Create a brick and capture its id.
    await clickCell(page, 5, 5);
    const brick = brickAt(page, 5, 5).first();
    await expect(brick).toBeVisible({ timeout: 8000 });
    const id = await brick.getAttribute('id');

    // Shift+click deletes it.
    await brick.click({ force: true, modifiers: ['Shift'] });
    await expect(page.locator(`#${id}`)).toHaveCount(0, { timeout: 8000 });
  });
});

test.describe('HTML morphing', () => {
  test('layout survives morph', async ({ page }) => {
    await page.goto('/');
    await join(page);

    await clickCell(page, 4, 4);
    await expect(brickAt(page, 4, 4).first()).toBeVisible({ timeout: 8000 });

    // Grid layout still intact after morphs.
    await expect(page.locator('#grid-viewport')).toBeVisible();
    await expect(page.locator('#grid-container')).toBeVisible();
  });
});

test.describe('drag and drop', () => {
  test('dragging a brick moves it to a new cell', async ({ page }) => {
    await page.goto('/');
    await join(page);

    // Create a brick at (2, 2) and capture its id.
    await clickCell(page, 2, 2);
    const brick = brickAt(page, 2, 2).first();
    await expect(brick).toBeVisible({ timeout: 8000 });
    const id = await brick.getAttribute('id');

    const srcBox = await brick.boundingBox();
    expect(srcBox).toBeTruthy();
    const dstCell = page.locator('button[data-cell-x="6"][data-cell-y="2"]');
    const dstBox = await dstCell.boundingBox();
    expect(dstBox).toBeTruthy();

    await page.mouse.move(srcBox!.x + srcBox!.width / 2, srcBox!.y + srcBox!.height / 2);
    await page.mouse.down();
    await page.mouse.move(dstBox!.x + dstBox!.width / 2, dstBox!.y + dstBox!.height / 2, { steps: 10 });
    await page.mouse.up();

    // The same brick now reports the destination cell.
    await expect(page.locator(`#${id}`)).toHaveAttribute('data-x', '6', { timeout: 8000 });
    await expect(page.locator(`#${id}`)).toHaveAttribute('data-y', '2', { timeout: 8000 });
  });
});

test.describe('multi-user', () => {
  test('brick appears for both users', async ({ browser }) => {
    const [ctx1, ctx2] = await Promise.all([browser.newContext(), browser.newContext()]);
    const [p1, p2] = await Promise.all([ctx1.newPage(), ctx2.newPage()]);

    await Promise.all([p1.goto('/'), p2.goto('/')]);
    await Promise.all([join(p1, 'One'), join(p2, 'Two')]);

    const before1 = await brickAt(p1, 1, 1).count();
    const before2 = await brickAt(p2, 1, 1).count();

    await clickCell(p1, 1, 1);

    await expect(brickAt(p1, 1, 1)).toHaveCount(before1 + 1, { timeout: 8000 });
    await expect(brickAt(p2, 1, 1)).toHaveCount(before2 + 1, { timeout: 8000 });

    await Promise.all([ctx1.close(), ctx2.close()]);
  });
});
