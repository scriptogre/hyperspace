import { test, expect } from '@playwright/test';

const shot = (page, name) => page.screenshot({ path: `test-results/walkthrough-${name}.png`, fullPage: true });

test('full interactive walkthrough', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', (err) => errors.push(err.message));

  // 1. Load page
  await page.goto('/');
  await page.waitForSelector('#console-log:has-text("joined")');
  await shot(page, '01-initial');

  // 2. Click a grid cell to create a block at (0,7) — use corner cells unlikely to collide
  await page.click('button[data-x="0"][data-y="7"]', { force: true });
  await expect(page.locator('aside')).toContainText('(0, 7)', { timeout: 5000 });
  await page.waitForTimeout(500);
  await shot(page, '02-one-block');

  // 3. Check console shows "block created"
  await expect(page.locator('#console-log')).toContainText(/block created/, { timeout: 5000 });

  // 4. Add a few more blocks at different positions
  await page.click('button[data-x="7"][data-y="0"]', { force: true });
  await expect(page.locator('aside')).toContainText('(7, 0)', { timeout: 5000 });
  await page.click('button[data-x="0"][data-y="6"]', { force: true });
  await expect(page.locator('aside')).toContainText('(0, 6)', { timeout: 5000 });
  await page.click('button[data-x="7"][data-y="1"]', { force: true });
  await expect(page.locator('aside')).toContainText('(7, 1)', { timeout: 5000 });
  await page.waitForTimeout(500);
  await shot(page, '03-four-blocks');

  // 6. Delete a block — hover sidebar entry, click ×
  const blockEntry = page.locator('aside .group', { hasText: '(0, 7)' }).first();
  await blockEntry.scrollIntoViewIfNeeded();
  await blockEntry.hover();
  await page.waitForTimeout(200);
  await shot(page, '04-hover-delete');
  await blockEntry.locator('button').click();
  await expect(page.locator('#console-log')).toContainText(/block deleted/, { timeout: 5000 });
  await page.waitForTimeout(500);
  await shot(page, '05-after-delete');

  // 7. Use + Block button (random position)
  const blocksBeforeRandom = await page.locator('[id^="block-"]').count();
  await page.click('button:has-text("+ Block")');
  await expect(page.locator('[id^="block-"]')).toHaveCount(blocksBeforeRandom + 1, { timeout: 5000 });
  await page.waitForTimeout(500);
  await shot(page, '06-after-random-block');

  // 9. Set name
  await page.fill('input[placeholder="Set name..."]', 'Alice');
  await page.press('input[placeholder="Set name..."]', 'Enter');
  await expect(page.locator('aside')).toContainText('Alice', { timeout: 5000 });
  await page.waitForTimeout(500);
  await shot(page, '07-set-name');

  // 10. Console should have multiple messages and no errors
  await shot(page, '08-final-console');

  // Verify ZERO JS errors throughout the entire walkthrough
  expect(errors).toEqual([]);
});
