const { chromium } = require('/opt/node22/lib/node_modules/playwright');
(async () => {
  const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' });
  // render at half intrinsic size: 896x1216 is plenty for a style reference
  const page = await browser.newPage({ viewport: { width: 896, height: 1216 } });
  await page.goto('file:///home/user/Rabota/qa/svg-frame.html', { waitUntil: 'networkidle' });
  await page.waitForTimeout(500);
  await page.screenshot({ path: 'qa/concierge-ref.png' });
  await browser.close();
})();
