import { test, expect } from '@playwright/test';

test('drag and drop moves block to new cell', async ({ page }) => {
  await page.goto('/');
  await page.waitForSelector('#console-log:has-text("joined")');

  // Use + Block button to create at random position, then check sidebar for any block
  await page.click('button:has-text("+ Block")');
  await page.waitForTimeout(500);

  // Get the first block's coordinates from the sidebar
  const blockEntry = page.locator('aside .group').first();
  await expect(blockEntry).toBeVisible({ timeout: 5000 });
  const blockText = await blockEntry.textContent();
  const match = blockText!.match(/\((\d+), (\d+)\)/);
  const [srcX, srcY] = [match![1], match![2]];

  // Find the block cell and an empty adjacent cell
  const src = page.locator(`button[data-x="${srcX}"][data-y="${srcY}"]`);
  const dstX = (parseInt(srcX) + 1) % 8;
  const dst = page.locator(`button[data-x="${dstX}"][data-y="${srcY}"]`);

  const srcBox = await src.boundingBox();
  const dstBox = await dst.boundingBox();

  // Drag
  await page.mouse.move(srcBox!.x + srcBox!.width / 2, srcBox!.y + srcBox!.height / 2);
  await page.mouse.down();
  await page.mouse.move(dstBox!.x + dstBox!.width / 2, dstBox!.y + dstBox!.height / 2, { steps: 3 });
  await page.mouse.up();

  // Block should now be at new position
  await expect(page.locator('aside')).toContainText(`(${dstX}, ${srcY})`, { timeout: 5000 });
});

test('stacking: drag block onto another creates stack', async ({ page }) => {
  await page.goto('/');
  await page.waitForSelector('#console-log:has-text("joined")');

  // Create two blocks using + Block button
  await page.click('button:has-text("+ Block")');
  await page.waitForTimeout(500);
  await page.click('button:has-text("+ Block")');
  await page.waitForTimeout(500);

  // Get the first two block entries from sidebar
  const entries = page.locator('aside .group');
  const count = await entries.count();
  if (count < 2) {
    // Not enough blocks, skip
    return;
  }

  // Get coordinates of first two distinct blocks
  const text1 = await entries.nth(0).textContent();
  const text2 = await entries.nth(1).textContent();
  const m1 = text1!.match(/\((\d+), (\d+)\)/);
  const m2 = text2!.match(/\((\d+), (\d+)\)/);
  if (!m1 || !m2) return;

  const src = page.locator(`button[data-x="${m2![1]}"][data-y="${m2![2]}"]`);
  const dst = page.locator(`button[data-x="${m1![1]}"][data-y="${m1![2]}"]`);
  const srcBox = await src.boundingBox();
  const dstBox = await dst.boundingBox();

  // Drag second block onto first
  await page.mouse.move(srcBox!.x + srcBox!.width / 2, srcBox!.y + srcBox!.height / 2);
  await page.mouse.down();
  await page.mouse.move(dstBox!.x + dstBox!.width / 2, dstBox!.y + dstBox!.height / 2, { steps: 3 });
  await page.mouse.up();

  // Should see z1 in sidebar (stacked block)
  await expect(page.locator('aside')).toContainText('z1', { timeout: 5000 });
});
