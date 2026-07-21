const { chromium } = require('/opt/node22/lib/node_modules/playwright');
(async () => {
  const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' });
  for (const [name, url] of [['ref','file:///home/user/Rabota/reference/lift-6-updated.html'],['new','http://localhost:4173/']]) {
    const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
    await page.goto(url, { waitUntil: 'networkidle' });
    await page.waitForTimeout(1000);
    const r = await page.evaluate(() => {
      const el = document.querySelector('.concierge-svg');
      const v = document.querySelector('.hero-visual');
      const b = el.getBoundingClientRect(), vb = v.getBoundingClientRect();
      return { svg: [b.x, b.y, b.width, b.height], visual: [vb.x, vb.y, vb.width, vb.height] };
    });
    console.log(name, JSON.stringify(r));
    await page.close();
  }
  await browser.close();
})();
