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

test('no console errors after block creation', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', (err) => errors.push(err.message));

  await page.goto('/');
  await page.waitForSelector('#console-log:has-text("connected")');

  // Create a block and wait for morph
  await page.click('button:has-text("+ Block")');
  await page.waitForTimeout(2000);

  // Should have zero JS errors
  expect(errors).toEqual([]);
});

test('server console messages appear after block creation', async ({ page }) => {
  await page.goto('/');
  await page.waitForSelector('#console-log:has-text("connected")');

  await page.click('button:has-text("+ Block")');

  // Server should broadcast "block created at (x,y)" to the console
  await expect(page.locator('#console-log')).toContainText(/block created at \(\d,\d\)/, { timeout: 5000 });
});

test('page remains intact after block creation', async ({ page }) => {
  await page.goto('/');
  await page.waitForSelector('#console-log:has-text("connected")');

  await expect(page.locator('h1:has-text("Hyperspace")')).toBeVisible();
  await expect(page.locator('.iso-grid')).toBeVisible();

  const blocksBefore = await page.locator('.iso-block').count();

  await page.click('button:has-text("+ Block")');
  await expect(page.locator('.iso-block')).toHaveCount(blocksBefore + 1, { timeout: 5000 });

  // Layout still intact after morph
  await expect(page.locator('h1:has-text("Hyperspace")')).toBeVisible();
  await expect(page.locator('.iso-grid')).toBeVisible();
  await expect(page.locator('#console-log')).toBeVisible();
  await expect(page.locator('button:has-text("+ Block")')).toBeVisible();
});

test('sidebar updates with block info', async ({ page }) => {
  await page.goto('/');
  await page.waitForSelector('#console-log:has-text("connected")');

  const blocksBefore = await page.locator('.iso-block').count();
  await page.click('button:has-text("+ Block")');
  await expect(page.locator('.iso-block')).toHaveCount(blocksBefore + 1, { timeout: 5000 });

  await expect(page.locator('aside')).toContainText('Blocks');
  await expect(page.locator('aside')).toContainText(/\(\d,\d\)/);
});

test('clicking grid cell creates block at that position', async ({ page }) => {
  await page.goto('/');
  await page.waitForSelector('#console-log:has-text("connected")');

  const blocksBefore = await page.locator('.iso-block').count();

  await page.click('.iso-cell[data-x="2"][data-y="3"]');
  await expect(page.locator('.iso-block')).toHaveCount(blocksBefore + 1, { timeout: 5000 });

  await expect(page.locator('aside')).toContainText('(2,3)');
});

test('delete button removes a block', async ({ page }) => {
  await page.goto('/');
  await page.waitForSelector('#console-log:has-text("connected")');

  // Create a block first
  await page.click('.iso-cell[data-x="5"][data-y="5"]');
  await expect(page.locator('aside')).toContainText('(5,5)', { timeout: 5000 });

  const blocksBefore = await page.locator('.iso-block').count();

  // Hover the block entry in sidebar to reveal × button, then click it
  const blockEntry = page.locator('aside .group', { hasText: '(5,5)' });
  await blockEntry.hover();
  await blockEntry.locator('button').click();

  // Block count should decrease
  await expect(page.locator('.iso-block')).toHaveCount(blocksBefore - 1, { timeout: 5000 });

  // Console should show deletion message
  await expect(page.locator('#console-log')).toContainText(/block deleted/, { timeout: 5000 });
});

test('multi-user sync: block appears in both tabs', async ({ browser }) => {
  const [c1, c2] = await Promise.all([browser.newContext(), browser.newContext()]);
  const [p1, p2] = await Promise.all([c1.newPage(), c2.newPage()]);
  await Promise.all([p1.goto('http://localhost:8080'), p2.goto('http://localhost:8080')]);
  await Promise.all([
    p1.waitForSelector('#console-log:has-text("connected")'),
    p2.waitForSelector('#console-log:has-text("connected")'),
  ]);

  const before = await p2.locator('.iso-block').count();

  await p1.click('button:has-text("+ Block")');
  await expect(p2.locator('.iso-block')).toHaveCount(before + 1, { timeout: 5000 });

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
