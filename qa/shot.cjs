// usage: node qa/shot.cjs <url> <outPrefix>
const { chromium } = require('/opt/node22/lib/node_modules/playwright');
const [,, url, prefix] = process.argv;
(async () => {
  const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' });
  const shots = [
    { w: 1440, h: 900, name: 'desktop' },
    { w: 390, h: 844, name: 'mobile' },
  ];
  for (const s of shots) {
    const page = await browser.newPage({ viewport: { width: s.w, height: s.h } });
    await page.goto(url, { waitUntil: 'networkidle' });
    await page.waitForTimeout(2200);
    await page.screenshot({ path: `${prefix}-${s.name}-viewport.png` });
    const height = await page.evaluate(() => document.body.scrollHeight);
    console.log(`${s.name}: pageHeight=${height}`);
    await page.addStyleTag({ content: '*,*::before,*::after{transition:none!important;animation:none!important}' });
    await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
    await page.waitForTimeout(800);
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.waitForTimeout(800);
    await page.screenshot({ path: `${prefix}-${s.name}-full.png`, fullPage: true });
    await page.close();
  }
  await browser.close();
})();
