import { test, expect, Page } from '@playwright/test';

/** Wait for WS to be connected and subscription applied (morphed at least once). */
async function waitForReady(page: Page) {
  await page.waitForFunction(
    () => localStorage.getItem('stdb_token') !== null,
    { timeout: 10_000 },
  );
  await expect(page.locator('#console-log')).toContainText('joined', { timeout: 10_000 });
}

/** Click a grid cell at the given coordinates. */
async function clickCell(page: Page, x: number, y: number) {
  const cell = page.locator(`button[data-cell-x="${x}"][data-cell-y="${y}"]`);
  await cell.click({ force: true });
}

test.describe('page load', () => {
  test('serves HTML with grid and player setup', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('#grid-viewport')).toBeVisible();
    await expect(page.locator('#player-setup')).toBeVisible();
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
});

test.describe('reducer calls', () => {
  test('clicking a grid cell creates a brick', async ({ page }) => {
    await page.goto('/');
    await waitForReady(page);

    const x = 10;
    const y = 0;
    const countBefore = await page.locator(`[data-brick-id][data-cell-x="${x}"][data-cell-y="${y}"]`).count();

    await clickCell(page, x, y);

    // A new brick should appear at that cell (unless already at limit)
    if (countBefore < 5) {
      await expect(page.locator(`[data-brick-id][data-cell-x="${x}"][data-cell-y="${y}"]`))
        .toHaveCount(countBefore + 1, { timeout: 8000 });
    }
  });

  test('brick appears after clicking grid cell', async ({ page }) => {
    await page.goto('/');
    await waitForReady(page);

    const x = 11, y = 0;
    const countBefore = await page.locator(`[data-brick-id][data-cell-x="${x}"][data-cell-y="${y}"]`).count();

    await clickCell(page, x, y);

    if (countBefore < 5) {
      await expect(page.locator(`[data-brick-id][data-cell-x="${x}"][data-cell-y="${y}"]`))
        .toHaveCount(countBefore + 1, { timeout: 8000 });
    }
  });

  test('shift+clicking a brick deletes it', async ({ page }) => {
    await page.goto('/');
    await waitForReady(page);

    // Create a brick first
    await clickCell(page, 5, 5);

    // Wait for at least 1 block
    const cellBricks = page.locator('[data-brick-id][data-cell-x="5"][data-cell-y="5"]');
    await expect(cellBricks.first()).toBeVisible({ timeout: 8000 });
    const blocksBefore = await page.locator('[id^="block-"]').count();

    // Shift+click the brick to delete
    const brickFace = cellBricks.first();
    await brickFace.click({ force: true, modifiers: ['Shift'] });

    // Wait for block count to decrease
    await expect(page.locator('[id^="block-"]')).toHaveCount(blocksBefore - 1, {
      timeout: 8000,
    });
  });
});

test.describe('HTML morphing', () => {
  test('layout survives morph', async ({ page }) => {
    await page.goto('/');
    await waitForReady(page);

    // Create a brick
    await clickCell(page, 4, 4);
    await expect(page.locator('[id^="block-"]').first()).toBeVisible({ timeout: 8000 });

    // Layout still intact
    await expect(page.locator('#grid-viewport')).toBeVisible();
    await expect(page.locator('#player-setup')).toBeVisible();
    await expect(page.locator('input[name="set_name"]')).toBeVisible();
  });

  test('console log shows join event', async ({ page }) => {
    await page.goto('/');
    await waitForReady(page);
    await expect(page.locator('#console-log')).toContainText('joined', { timeout: 8000 });
  });
});

test.describe('drag and drop', () => {
  test('dragging a brick moves it to a new cell', async ({ page }) => {
    await page.goto('/');
    await waitForReady(page);

    // Create a brick at (2, 2) — unlikely to collide with other tests
    await clickCell(page, 2, 2);
    await expect(page.locator('[data-brick-id][data-cell-x="2"][data-cell-y="2"]')).toBeVisible({ timeout: 8000 });

    // Get the brick we just created
    const brick = page.locator('[data-brick-id][data-cell-x="2"][data-cell-y="2"]').first();
    const srcBox = await brick.boundingBox();
    expect(srcBox).toBeTruthy();

    // Pick a destination cell a few cells away
    const dstCell = page.locator('button[data-cell-x="6"][data-cell-y="2"]');
    const dstBox = await dstCell.boundingBox();
    expect(dstBox).toBeTruthy();

    // Drag: mousedown, move with steps, mouseup
    await page.mouse.move(srcBox!.x + srcBox!.width / 2, srcBox!.y + srcBox!.height / 2);
    await page.mouse.down();
    await page.mouse.move(dstBox!.x + dstBox!.width / 2, dstBox!.y + dstBox!.height / 2, { steps: 10 });
    await page.mouse.up();

    // Brick should move away from (2,2) and land at (6,2)
    await expect(page.locator('[data-brick-id][data-cell-x="2"][data-cell-y="2"]')).toHaveCount(0, { timeout: 8000 });
    await expect(page.locator('[data-brick-id][data-cell-x="6"][data-cell-y="2"]')).toHaveCount(1, { timeout: 8000 });
  });
});

test.describe('multi-user', () => {
  test('brick appears for both users', async ({ browser }) => {
    const [ctx1, ctx2] = await Promise.all([
      browser.newContext(),
      browser.newContext(),
    ]);
    const [p1, p2] = await Promise.all([ctx1.newPage(), ctx2.newPage()]);

    await Promise.all([
      p1.goto('http://localhost:3000'),
      p2.goto('http://localhost:3000'),
    ]);

    await Promise.all([waitForReady(p1), waitForReady(p2)]);

    const target = '[data-brick-id][data-cell-x="0"][data-cell-y="0"]';
    const beforeP1 = await p1.locator(target).count();
    const beforeP2 = await p2.locator(target).count();

    // Player 1 creates a brick at an edge position unlikely to have prior bricks
    await clickCell(p1, 0, 0);

    // Player 1 should see more bricks
    await expect(p1.locator(target)).toHaveCount(beforeP1 + 1, { timeout: 8000 });

    // Player 2 should also see the same cell update
    await expect(p2.locator(target)).toHaveCount(beforeP2 + 1, { timeout: 8000 });

    await Promise.all([ctx1.close(), ctx2.close()]);
  });
});
