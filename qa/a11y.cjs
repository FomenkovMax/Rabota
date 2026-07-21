const { chromium } = require('/opt/node22/lib/node_modules/playwright');
(async () => {
  const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' });
  // keyboard navigation
  let page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  await page.goto('http://localhost:4173/', { waitUntil: 'networkidle' });
  const focused = [];
  for (let i = 0; i < 4; i++) {
    await page.keyboard.press('Tab');
    focused.push(await page.evaluate(() => {
      const el = document.activeElement;
      const st = getComputedStyle(el);
      return el.className + ' <' + el.tagName + '> outline:' + st.outlineStyle;
    }));
  }
  console.log('tab order:', JSON.stringify(focused, null, 1));
  await page.keyboard.press('Shift+Tab'); await page.keyboard.press('Shift+Tab'); await page.keyboard.press('Shift+Tab');
  await page.focus('.cta');
  await page.keyboard.press('Enter');
  await page.waitForTimeout(1500);
  console.log('after Enter on CTA, scrollY:', await page.evaluate(() => scrollY), 'hash:', await page.evaluate(() => location.hash));
  await page.close();

  // reduced motion
  page = await browser.newPage({ viewport: { width: 1440, height: 900 }, reducedMotion: 'reduce' });
  await page.goto('http://localhost:4173/', { waitUntil: 'networkidle' });
  await page.waitForTimeout(1500);
  const rm = await page.evaluate(() => {
    const doors = document.querySelector('.doors');
    const arrow = document.querySelector('.hud .arrow');
    const layer = document.querySelector('.scene-layer');
    return {
      doorsDisplay: getComputedStyle(doors).display,
      arrowAnimation: getComputedStyle(arrow).animationName,
      sceneTransition: getComputedStyle(layer).transitionDuration,
      scrollBehavior: getComputedStyle(document.documentElement).scrollBehavior,
    };
  });
  console.log('reduced-motion:', JSON.stringify(rm));
  await page.screenshot({ path: 'qa/screens/new-desktop-reduced-motion.png' });
  await browser.close();
})();
