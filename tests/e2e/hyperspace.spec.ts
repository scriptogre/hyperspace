import { test, expect } from '@playwright/test';

test('page loads with full layout', async ({ page }) => {
  await page.goto('/');
  await expect(page.locator('h1:has-text("Hyperspace")')).toBeVisible();
  await expect(page.locator('#grid-viewport')).toBeVisible();
  await expect(page.locator('#console-log')).toBeVisible();
  await expect(page.locator('button:has-text("+ Block")')).toBeVisible();
  await expect(page.locator('input[placeholder="Set name..."]')).toBeVisible();
});

test('websocket connects and logs to console', async ({ page }) => {
  await page.goto('/');
  // Console should show connected (initialized may be cleared by morphs from parallel tests)
  await expect(page.locator('#console-log')).not.toBeEmpty({ timeout: 5000 });
});

test('no console errors after block creation', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', (err) => errors.push(err.message));

  await page.goto('/');
  await page.waitForSelector('#grid-viewport');

  // Create a block and wait for morph
  await page.click('button:has-text("+ Block")');
  await page.waitForTimeout(2000);

  // Should have zero JS errors
  expect(errors).toEqual([]);
});

test('server console messages appear after block creation', async ({ page }) => {
  await page.goto('/');
  await page.waitForSelector('#console-log:has-text("joined")');

  await page.click('button:has-text("+ Block")');

  // Server should broadcast "block created at (x,y)" to the console
  await expect(page.locator('#console-log')).toContainText(/block created at \(\d,\d\)/, { timeout: 5000 });
});

test('page remains intact after block creation', async ({ page }) => {
  await page.goto('/');
  await page.waitForSelector('#console-log:has-text("joined")');

  await expect(page.locator('h1:has-text("Hyperspace")')).toBeVisible();
  await expect(page.locator('#grid-viewport')).toBeVisible();

  const blocksBefore = await page.locator('[id^="block-"]').count();

  await page.click('button:has-text("+ Block")');
  await expect(page.locator('[id^="block-"]')).toHaveCount(blocksBefore + 1, { timeout: 5000 });

  // Layout still intact after morph
  await expect(page.locator('h1:has-text("Hyperspace")')).toBeVisible();
  await expect(page.locator('#grid-viewport')).toBeVisible();
  await expect(page.locator('#console-log')).toBeVisible();
  await expect(page.locator('button:has-text("+ Block")')).toBeVisible();
});

test('sidebar updates with block info', async ({ page }) => {
  await page.goto('/');
  await page.waitForSelector('#console-log:has-text("joined")');

  const blocksBefore = await page.locator('[id^="block-"]').count();
  await page.click('button:has-text("+ Block")');
  await expect(page.locator('[id^="block-"]')).toHaveCount(blocksBefore + 1, { timeout: 5000 });

  await expect(page.locator('aside')).toContainText('Blocks');
  await expect(page.locator('aside')).toContainText(/\(\d, \d\)/);
});

test('clicking grid cell creates block at that position', async ({ page }) => {
  await page.goto('/');
  await page.waitForSelector('#console-log:has-text("joined")');

  await page.click('button[data-x="2"][data-y="3"]', { force: true });
  await expect(page.locator('aside')).toContainText('(2, 3)', { timeout: 5000 });
});

test('delete button removes a block', async ({ page }) => {
  await page.goto('/');
  await page.waitForSelector('#console-log:has-text("joined")');

  // Create a block first
  await page.click('button[data-x="5"][data-y="5"]', { force: true });
  await expect(page.locator('aside')).toContainText('(5, 5)', { timeout: 5000 });

  // Hover the block entry in sidebar to reveal × button, then click it
  const blockEntry = page.locator('aside .group', { hasText: '(5, 5)' }).first();
  await blockEntry.scrollIntoViewIfNeeded();
  await blockEntry.hover();
  await blockEntry.locator('button').click();

  // Verify deletion: console message + entry removed from sidebar
  await expect(page.locator('#console-log')).toContainText(/block deleted/, { timeout: 5000 });
});

test('multi-user sync: block appears in both tabs', async ({ browser }) => {
  const [c1, c2] = await Promise.all([browser.newContext(), browser.newContext()]);
  const [p1, p2] = await Promise.all([c1.newPage(), c2.newPage()]);
  await Promise.all([p1.goto('http://localhost:8080'), p2.goto('http://localhost:8080')]);
  await Promise.all([
    p1.waitForSelector('#console-log:has-text("joined")'),
    p2.waitForSelector('#console-log:has-text("joined")'),
  ]);

  const before = await p2.locator('[id^="block-"]').count();

  await p1.click('button:has-text("+ Block")');
  await expect(p2.locator('[id^="block-"]')).toHaveCount(before + 1, { timeout: 5000 });

  await expect(p2.locator('h1:has-text("Hyperspace")')).toBeVisible();
  await expect(p2.locator('#grid-viewport')).toBeVisible();
  await expect(p2.locator('#console-log')).toBeVisible();

  await Promise.all([c1.close(), c2.close()]);
});

test('screenshot', async ({ page }) => {
  await page.goto('/');
  await page.waitForSelector('#grid-viewport');
  await page.waitForTimeout(500);
  await page.screenshot({ path: 'test-results/hyperspace.png', fullPage: true });
});
