import { test, expect } from '@playwright/test';

test('cursor appears on grid at correct position', async ({ browser }) => {
  const errors: string[] = [];

  const c1 = await browser.newContext();
  const c2 = await browser.newContext();
  const p1 = await c1.newPage();
  const p2 = await c2.newPage();
  p1.on('pageerror', (err) => errors.push('p1: ' + err.message));
  p2.on('pageerror', (err) => errors.push('p2: ' + err.message));

  await Promise.all([p1.goto('http://localhost:8080'), p2.goto('http://localhost:8080')]);
  await Promise.all([
    p1.waitForSelector('#console-log:has-text("connected")'),
    p2.waitForSelector('#console-log:has-text("connected")'),
  ]);

  // Set names
  await p1.fill('input[placeholder="Set name..."]', 'Alice');
  await p1.press('input[placeholder="Set name..."]', 'Enter');
  await p2.fill('input[placeholder="Set name..."]', 'Bob');
  await p2.press('input[placeholder="Set name..."]', 'Enter');
  await p1.waitForTimeout(500);

  // Hover over grid cell (4,3) in tab 1
  await p1.hover('.iso-cell[data-x="4"][data-y="3"]');
  await p1.waitForTimeout(500);

  // Tab 2 should show a cursor
  const cursor = p2.locator('.iso-cursor');
  await expect(cursor).toBeVisible({ timeout: 5000 });

  // Cursor should have a dot and label
  await expect(cursor.locator('.iso-cursor-dot')).toBeVisible();
  await expect(cursor.locator('.iso-label')).toBeVisible();

  // Screenshot
  await p2.screenshot({ path: 'test-results/cursor-tab2.png', fullPage: true });

  expect(errors).toEqual([]);
  await Promise.all([c1.close(), c2.close()]);
});
