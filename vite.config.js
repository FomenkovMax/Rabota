import { defineConfig } from 'vite';

const CRITICAL_MARK = '/*! CRITICAL-END */';

// Inline the above-the-fold part of the stylesheet into <head> and load the
// rest asynchronously; the split point is the CRITICAL-END marker in styles.css.
function inlineCriticalCss() {
  return {
    name: 'inline-critical-css',
    apply: 'build',
    transformIndexHtml: {
      order: 'post',
      handler(html, ctx) {
        const cssEntry = Object.entries(ctx.bundle || {}).find(([name]) => name.endsWith('.css'));
        if (!cssEntry) return html;
        const [fileName, asset] = cssEntry;
        const css = asset.source.toString();
        const markAt = css.indexOf(CRITICAL_MARK);
        const splitAt = markAt !== -1 ? markAt : css.indexOf('.penthouse{');
        const critical = splitAt !== -1 ? css.slice(0, splitAt) : css;
        const rest = splitAt !== -1 ? css.slice(splitAt + (markAt !== -1 ? CRITICAL_MARK.length : 0)) : '';
        asset.source = rest;

        const linkRe = new RegExp(`<link rel="stylesheet"[^>]*href="[^"]*${fileName.split('/').pop()}"[^>]*>`);
        const async =
          `<style>${critical}</style>` +
          `<link rel="preload" href="/${fileName}" as="style" onload="this.onload=null;this.rel='stylesheet'">` +
          `<noscript><link rel="stylesheet" href="/${fileName}"></noscript>`;
        if (!linkRe.test(html)) throw new Error('stylesheet link not found in html');
        return html.replace(linkRe, async);
      },
    },
  };
}

export default defineConfig({
  build: {
    target: 'es2018',
    assetsInlineLimit: 2048,
    modulePreload: { polyfill: false },
  },
  plugins: [inlineCriticalCss()],
});
