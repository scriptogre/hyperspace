import { test, expect } from '@playwright/test';

const shot = (page, name) => page.screenshot({ path: `test-results/walkthrough-${name}.png`, fullPage: true });

test('full interactive walkthrough', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', (err) => errors.push(err.message));

  // 1. Load page
  await page.goto('/');
  await page.waitForSelector('#console-log:has-text("connected")');
  await shot(page, '01-initial');

  // 2. Click a grid cell to create a block at (3,2)
  const initialBlocks = await page.locator('.iso-block').count();
  await page.click('.iso-cell[data-x="3"][data-y="2"]');
  await expect(page.locator('.iso-block')).toHaveCount(initialBlocks + 1, { timeout: 5000 });
  await page.waitForTimeout(500);
  await shot(page, '02-one-block');

  // 3. Check console shows "block created"
  await expect(page.locator('#console-log')).toContainText(/block created/, { timeout: 5000 });

  // 4. Add a few more blocks at different positions
  await page.click('.iso-cell[data-x="1"][data-y="1"]');
  await expect(page.locator('.iso-block')).toHaveCount(initialBlocks + 2, { timeout: 5000 });
  await page.click('.iso-cell[data-x="6"][data-y="5"]');
  await expect(page.locator('.iso-block')).toHaveCount(initialBlocks + 3, { timeout: 5000 });
  await page.click('.iso-cell[data-x="4"][data-y="7"]');
  await expect(page.locator('.iso-block')).toHaveCount(initialBlocks + 4, { timeout: 5000 });
  await page.waitForTimeout(500);
  await shot(page, '03-four-blocks');

  // 5. Verify sidebar lists all blocks
  await expect(page.locator('aside')).toContainText(`Blocks · ${initialBlocks + 4}`);
  await expect(page.locator('aside')).toContainText('(3,2)');
  await expect(page.locator('aside')).toContainText('(1,1)');
  await expect(page.locator('aside')).toContainText('(6,5)');
  await expect(page.locator('aside')).toContainText('(4,7)');

  // 6. Delete a block — hover sidebar entry, click ×
  const blockEntry = page.locator('aside .group', { hasText: '(3,2)' }).first();
  await blockEntry.hover();
  await page.waitForTimeout(200);
  await shot(page, '04-hover-delete');
  await blockEntry.locator('button').click();
  await expect(page.locator('.iso-block')).toHaveCount(initialBlocks + 3, { timeout: 5000 });
  await expect(page.locator('#console-log')).toContainText(/block deleted/, { timeout: 5000 });
  await page.waitForTimeout(500);
  await shot(page, '05-after-delete');

  // 7. Verify sidebar updated
  await expect(page.locator('aside')).toContainText(`Blocks · ${initialBlocks + 3}`);

  // 8. Use + Block button (random position)
  await page.click('button:has-text("+ Block")');
  await expect(page.locator('.iso-block')).toHaveCount(initialBlocks + 4, { timeout: 5000 });
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
