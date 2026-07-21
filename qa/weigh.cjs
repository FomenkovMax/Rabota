const { chromium } = require('/opt/node22/lib/node_modules/playwright');
(async () => {
  const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' });
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  const items = [];
  page.on('response', async (res) => {
    try {
      const body = await res.body();
      items.push({ url: res.url().split('/').pop() || '/', bytes: body.length, type: res.request().resourceType() });
    } catch {}
  });
  await page.goto('http://localhost:4173/', { waitUntil: 'networkidle' });
  await page.waitForTimeout(3000); // let idle-hydrated scenes load too, listed separately below
  let firstScreen = 0;
  for (const i of items.sort((a,b)=>b.bytes-a.bytes)) {
    const deferred = /scene-cabin|scene-top|icon-floor-0[2-9]|mentor/.test(i.url);
    if (!deferred) firstScreen += i.bytes;
    console.log(`${deferred?'[deferred]':'[first]   '} ${(i.bytes/1024).toFixed(1).padStart(7)} KB  ${i.type.padEnd(10)} ${i.url}`);
  }
  console.log(`\nFIRST SCREEN TOTAL (uncompressed bodies): ${(firstScreen/1024).toFixed(1)} KB`);
  await browser.close();
})();
