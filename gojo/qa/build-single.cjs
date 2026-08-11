// Inlines style.css + main.js into one self-contained page.
// Used for publishing where external requests are blocked (Artifact CSP),
// so the webfont link is dropped and the fallback stacks are made explicit.
const fs = require('fs');
const path = require('path');
const dir = path.join(__dirname, '..');
const out = process.argv[2];

const html = fs.readFileSync(path.join(dir, 'index.html'), 'utf8');
const js = fs.readFileSync(path.join(dir, 'main.js'), 'utf8');
let css = fs.readFileSync(path.join(dir, 'style.css'), 'utf8');

const STACKS = {
  serif: "'Hiragino Mincho ProN','Yu Mincho','Songti SC','MS Mincho',serif",
  gothic: "'Hiragino Kaku Gothic ProN','Yu Gothic','Noto Sans JP',Meiryo,system-ui,sans-serif",
  display: "'Optima','Palatino Linotype',Palatino,'Times New Roman',serif",
  mono: "'Helvetica Neue',Helvetica,Arial,sans-serif"
};
for (const [k, v] of Object.entries(STACKS)) {
  css = css.replace(new RegExp('--' + k + ':[^;]+;'), '--' + k + ':' + v + ';');
}

const body = html.slice(html.indexOf('<body>') + 6, html.indexOf('<script src='));
/* charset first: the page is mostly Japanese, and a host that serves it
   without a charset would otherwise render the whole thing as mojibake */
fs.writeFileSync(out,
  '<meta charset="utf-8">\n' +
  '<title>五条 悟 — GOJO SATORU</title>\n' +
  '<style>\n' + css + '\n</style>\n' +
  body + '\n<script>\n' + js + '\n<' + '/script>\n');
console.log('wrote', out, fs.statSync(out).size, 'bytes');
