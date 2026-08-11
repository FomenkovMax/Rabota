// usage: node gojo/qa/shot.cjs <url> <outDir>
// Captures the page at a set of scroll fractions plus the console log,
// so the procedural scrub can be eyeballed frame by frame.
const { chromium } = require('/opt/node22/lib/node_modules/playwright');
const [, , url, outDir] = process.argv;

const STOPS = [0, 0.06, 0.12, 0.18, 0.24, 0.32, 0.42, 0.52, 0.62, 0.72, 0.82, 0.9, 0.96];

(async () => {
  const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' });
  const errors = [];

  for (const s of [{ w: 1440, h: 900, name: 'desktop' }, { w: 390, h: 844, name: 'mobile' }]) {
    const page = await browser.newPage({ viewport: { width: s.w, height: s.h } });
    page.on('console', m => { if (m.type() === 'error') errors.push(`${s.name}: ${m.text()}`); });
    page.on('pageerror', e => errors.push(`${s.name}: ${e.message}`));

    await page.goto(url, { waitUntil: 'networkidle' });
    await page.waitForTimeout(2600); // let the loader finish
    await page.mouse.move(s.w * 0.72, s.h * 0.38);

    const height = await page.evaluate(() => document.documentElement.scrollHeight);
    console.log(`${s.name}: pageHeight=${height}`);

    for (const f of STOPS) {
      await page.evaluate(y => window.scrollTo(0, y), Math.round((height - s.h) * f));
      await page.waitForTimeout(600);
      await page.screenshot({ path: `${outDir}/${s.name}-${String(Math.round(f * 100)).padStart(3, '0')}.png` });
    }
    await page.close();
  }

  await browser.close();
  console.log(errors.length ? 'CONSOLE ERRORS:\n' + errors.join('\n') : 'no console errors');
})();
