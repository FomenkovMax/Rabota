const { chromium } = require('/opt/node22/lib/node_modules/playwright');
(async () => {
  const browser = await chromium.launch({
    executablePath: '/opt/pw-browsers/chromium',
    proxy: { server: process.env.HTTPS_PROXY || process.env.https_proxy },
  });
  for (const s of [{w:1440,h:900,name:'desktop'},{w:390,h:844,name:'mobile'}]) {
    const page = await browser.newPage({ viewport: { width: s.w, height: s.h } });
    await page.goto('https://lift-landing.netlify.app/', { waitUntil: 'networkidle', timeout: 60000 });
    await page.waitForTimeout(2200);
    await page.screenshot({ path: `qa/screens/live-${s.name}-viewport.png` });
    console.log(s.name, 'pageHeight=', await page.evaluate(() => document.body.scrollHeight));
    await page.close();
  }
  await browser.close();
})();
