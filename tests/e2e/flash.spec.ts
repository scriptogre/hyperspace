import { test, expect } from '@playwright/test';

test('modal gates user creation; chosen color persists; no flash on reload', async ({ page, context, request }) => {
  await context.clearCookies();
  await page.goto('http://localhost:3000/');
  await page.evaluate(() => localStorage.clear());

  // GET / never includes modal HTML (server gates it on identity).
  const html = await request.get('http://localhost:3000/').then(r => r.text());
  expect(html).not.toContain('welcome-modal');

  const sent: string[] = [];
  page.on('websocket', ws => {
    ws.on('framesent', f => {
      const s = String(f.payload);
      if (s.includes('CallReducer')) sent.push(s.slice(0, 250));
    });
  });

  // New visitor: WS broadcast adds modal.
  await page.goto('http://localhost:3000/');
  await page.waitForSelector('#welcome-modal', { timeout: 5000 });

  await page.locator('input[name=set_name]').fill('TestUser');
  await page.locator('.color-pick[data-color=Green]').click();
  await page.waitForTimeout(200);
  await page.locator('button[name=continue]').click();

  // complete_setup creates user with chosen color; modal disappears.
  await page.waitForSelector('#welcome-modal', { state: 'detached', timeout: 5000 });
  const setup = sent.find(s => s.includes('complete_setup'));
  expect(setup).toContain('TestUser');
  expect(setup).toContain('green');

  // Reload as returning user: modal must never appear (token persisted).
  await page.reload();
  await page.waitForLoadState('domcontentloaded');
  await page.waitForTimeout(2000);
  expect(await page.locator('#welcome-modal').count()).toBe(0);
});
