import { test, expect } from '@playwright/test';

// Verifies hx-live reactive bindings:
// 1. Continue button reactively disables until name + color picked.
// 2. Brick gains data-grabbing instantly on local drag, before server commit.

test.beforeEach(async ({ page }) => {
  await page.goto('http://localhost:3000/');
  await page.evaluate(() => localStorage.clear());
  await page.reload();
  await page.waitForLoadState('networkidle');
  await page.waitForTimeout(1000);
});

test('Continue button reactive disabled state', async ({ page }) => {
  const cont = page.locator('button[name=continue]');
  await expect(cont).toBeVisible();
  await expect(cont).toBeDisabled();

  await page.fill('input[name=set_name]', 'Tester');
  await expect(cont).toBeDisabled();

  await page.locator('button[data-color=Cyan]').click();
  await expect(cont).toBeEnabled();

  await page.fill('input[name=set_name]', '');
  await expect(cont).toBeDisabled();
});

test('brick gains data-grabbing instantly on drag', async ({ page }) => {
  await page.fill('input[name=set_name]', 'Dragger');
  await page.locator('button[data-color=Green]').click();
  await page.locator('button[name=continue]').click();
  await page.waitForTimeout(500);

  await page.locator('#cell-2-2').click();
  await page.waitForTimeout(500);

  const brick = page.locator('[data-brick-id]').first();
  await expect(brick).toBeVisible();
  await expect(brick).not.toHaveAttribute('data-grabbing', '');

  const box = await brick.boundingBox();
  if (!box) throw new Error('no brick box');

  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  await page.mouse.down();
  await page.mouse.move(box.x + box.width / 2 + 20, box.y + box.height / 2 + 20);

  await expect(brick).toHaveAttribute('data-grabbing', '');

  await page.mouse.up();
  await page.waitForTimeout(300);
  await expect(brick).not.toHaveAttribute('data-grabbing', '');
});

test('drag prediction: brick moves locally before server confirms', async ({ page }) => {
  await page.fill('input[name=set_name]', 'Predictor');
  await page.locator('button[data-color=Pink]').click();
  await page.locator('button[name=continue]').click();
  await page.waitForTimeout(500);

  await page.locator('#cell-8-8').click();
  await page.waitForTimeout(500);

  const brickId = await page.locator('[data-x="8"][data-y="8"]').first().getAttribute('data-brick-id');
  const brick = page.locator(`[data-brick-id="${brickId}"]`);
  const startCol = await brick.evaluate((el: HTMLElement) => el.style.gridColumn);

  const box = await brick.boundingBox();
  if (!box) throw new Error('no brick at 8,8');

  await page.mouse.move(box.x + 32, box.y + 32);
  await page.mouse.down();
  await page.mouse.move(box.x + 32 - 64, box.y + 32, { steps: 5 });

  // :style derives grid-column from data.predX (set by predict) before server confirms.
  await expect.poll(async () => brick.evaluate((el: HTMLElement) => el.style.gridColumn)).not.toBe(startCol);

  await page.mouse.up();
});

test('delete prediction: brick gets data-pending-delete instantly', async ({ page }) => {
  await page.fill('input[name=set_name]', 'Deleter');
  await page.locator('button[data-color=Purple]').click();
  await page.locator('button[name=continue]').click();
  await page.waitForTimeout(500);

  await page.locator('#cell-5-5').click();
  await page.waitForTimeout(500);

  const brick = page.locator('[data-brick-id]').first();
  await expect(brick).not.toHaveAttribute('data-pending-delete', '');

  const box = await brick.boundingBox();
  if (!box) throw new Error('no brick');

  await page.keyboard.down('Shift');
  await page.mouse.move(box.x + 32, box.y + 32);
  await page.mouse.down();

  await expect(brick).toHaveAttribute('data-pending-delete', '');

  await page.mouse.up();
  await page.keyboard.up('Shift');
});
