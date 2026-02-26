import { test, expect } from '@playwright/test';

test('page loads with full layout', async ({ page }) => {
  await page.goto('/');
  await expect(page.locator('h1:has-text("Hyperspace")')).toBeVisible();
  await expect(page.locator('.iso-grid')).toBeVisible();
  await expect(page.locator('#console-log')).toBeVisible();
  await expect(page.locator('button:has-text("+ Block")')).toBeVisible();
  await expect(page.locator('input[placeholder="Set name..."]')).toBeVisible();
});

test('websocket connects and logs to console', async ({ page }) => {
  await page.goto('/');
  await expect(page.locator('#console-log')).toContainText('initialized', { timeout: 3000 });
  await expect(page.locator('#console-log')).toContainText('connected', { timeout: 5000 });
});

test('page remains intact after block creation', async ({ page }) => {
  await page.goto('/');
  await page.waitForSelector('#console-log:has-text("connected")');

  // Verify layout before
  await expect(page.locator('h1:has-text("Hyperspace")')).toBeVisible();
  await expect(page.locator('.iso-grid')).toBeVisible();

  const blocksBefore = await page.locator('.iso-block').count();

  // Click + Block
  await page.click('button:has-text("+ Block")');

  // Wait for block to appear
  await expect(page.locator('.iso-block')).toHaveCount(blocksBefore + 1, { timeout: 5000 });

  // Verify layout is STILL intact after morph (page should not break)
  await expect(page.locator('h1:has-text("Hyperspace")')).toBeVisible();
  await expect(page.locator('.iso-grid')).toBeVisible();
  await expect(page.locator('#console-log')).toBeVisible();
  await expect(page.locator('button:has-text("+ Block")')).toBeVisible();
});

test('sidebar updates with block info', async ({ page }) => {
  await page.goto('/');
  await page.waitForSelector('#console-log:has-text("connected")');

  // Click + Block and verify sidebar shows block count update
  const blocksBefore = await page.locator('.iso-block').count();
  await page.click('button:has-text("+ Block")');
  await expect(page.locator('.iso-block')).toHaveCount(blocksBefore + 1, { timeout: 5000 });

  // Sidebar should show block coordinates (random position, match any coordinate)
  await expect(page.locator('aside')).toContainText('Blocks');
  await expect(page.locator('aside')).toContainText(/\(\d,\d\)/);
});

test('clicking grid cell creates block at that position', async ({ page }) => {
  await page.goto('/');
  await page.waitForSelector('#console-log:has-text("connected")');

  const blocksBefore = await page.locator('.iso-block').count();

  // Click the cell at (2,3)
  await page.click('.iso-cell[data-x="2"][data-y="3"]');
  await expect(page.locator('.iso-block')).toHaveCount(blocksBefore + 1, { timeout: 5000 });

  // Sidebar should show the exact coordinates
  await expect(page.locator('aside')).toContainText('(2,3)');
});

test('multi-user sync: block appears in both tabs', async ({ browser }) => {
  const [c1, c2] = await Promise.all([browser.newContext(), browser.newContext()]);
  const [p1, p2] = await Promise.all([c1.newPage(), c2.newPage()]);
  await Promise.all([p1.goto('http://localhost:8080'), p2.goto('http://localhost:8080')]);
  await Promise.all([
    p1.waitForSelector('#console-log:has-text("connected")'),
    p2.waitForSelector('#console-log:has-text("connected")'),
  ]);

  // Count blocks in page 2 before
  const before = await p2.locator('.iso-block').count();

  // Add block in page 1 via button
  await p1.click('button:has-text("+ Block")');

  // Verify block count increased in page 2
  await expect(p2.locator('.iso-block')).toHaveCount(before + 1, { timeout: 5000 });

  // Verify page 2 layout is still intact
  await expect(p2.locator('h1:has-text("Hyperspace")')).toBeVisible();
  await expect(p2.locator('.iso-grid')).toBeVisible();
  await expect(p2.locator('#console-log')).toBeVisible();

  await Promise.all([c1.close(), c2.close()]);
});

test('screenshot', async ({ page }) => {
  await page.goto('/');
  await page.waitForSelector('.iso-grid');
  await page.waitForTimeout(500);
  await page.screenshot({ path: 'test-results/hyperspace.png', fullPage: true });
});
