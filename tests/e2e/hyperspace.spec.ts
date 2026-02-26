import { test, expect } from '@playwright/test';

test('page loads with layout', async ({ page }) => {
  await page.goto('/');
  await expect(page.locator('text=Hyperspace')).toBeVisible();
  await expect(page.locator('.iso-grid')).toBeVisible();
  await expect(page.locator('#console-log')).toBeVisible();
});

test('websocket connects', async ({ page }) => {
  await page.goto('/');
  await expect(page.locator('#console-log')).toContainText('connected', { timeout: 5000 });
});

test('add block button works', async ({ page }) => {
  await page.goto('/');
  await page.waitForSelector('#console-log:has-text("connected")');
  await page.click('button:has-text("+ Block")');
  await expect(page.locator('.iso-block')).toBeVisible({ timeout: 3000 });
});

test('multi-user sync', async ({ browser }) => {
  const [c1, c2] = await Promise.all([browser.newContext(), browser.newContext()]);
  const [p1, p2] = await Promise.all([c1.newPage(), c2.newPage()]);
  await Promise.all([p1.goto('http://localhost:8080'), p2.goto('http://localhost:8080')]);
  await Promise.all([
    p1.waitForSelector('#console-log:has-text("connected")'),
    p2.waitForSelector('#console-log:has-text("connected")'),
  ]);

  // Place block in page 1
  await p1.click('.iso-cell[data-x="2"][data-y="2"]');

  // Verify in page 2
  await expect(p2.locator('text=(2,2)')).toBeVisible({ timeout: 5000 });

  await Promise.all([c1.close(), c2.close()]);
});

test('screenshot', async ({ page }) => {
  await page.goto('/');
  await page.waitForSelector('.iso-grid');
  await page.waitForTimeout(500);
  await page.screenshot({ path: 'test-results/hyperspace.png', fullPage: true });
});
