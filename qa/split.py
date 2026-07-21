import re, os

html = open('reference/lift-6-updated.html', encoding='utf-8').read()

# --- concierge SVG -> file ---
svg_start = html.index('<svg class="concierge-svg"')
svg_end = html.index('</svg>', html.index('recraft-signature')) + len('</svg>')
svg = html[svg_start:svg_end]
# strip recraft metadata block (non-rendering)
svg = re.sub(r'<metadata>.*?</metadata>', '', svg, flags=re.S)
# root element keeps width/height/viewBox/preserveAspectRatio; drop role/aria (moved to <img alt>)
svg = svg.replace(' role="img" aria-label="Консьерж открывает решётчатую дверь лифта"', '')
open('src/assets/img/concierge.svg', 'w', encoding='utf-8').write(svg)
print('concierge.svg bytes:', os.path.getsize('src/assets/img/concierge.svg'))

# --- CSS ---
css = html[html.index('<style>')+7 : html.index('</style>')]
print('css bytes:', len(css))

# replace font data URIs in order
font_names = [
 'jetbrains-mono-400-600-cyrillic-ext','jetbrains-mono-400-600-cyrillic','jetbrains-mono-400-600-latin',
 'oswald-500-700-cyrillic-ext','oswald-500-700-cyrillic','oswald-500-700-latin',
 'pt-serif-italic-400-cyrillic-ext','pt-serif-italic-400-cyrillic','pt-serif-italic-400-latin',
 'pt-serif-400-cyrillic-ext','pt-serif-400-cyrillic','pt-serif-400-latin',
 'pt-serif-700-cyrillic-ext','pt-serif-700-cyrillic','pt-serif-700-latin',
]
it = iter(font_names)
css = re.sub(r'url\(data:font/woff2;base64,[A-Za-z0-9+/=]+\)',
             lambda m: f"url('./assets/fonts/{next(it)}.woff2')", css)
# hero-visual webp
css = re.sub(r"url\('data:image/webp;base64,[A-Za-z0-9+/=]+'\)",
             "url('./assets/img/hero-visual-bg.webp')", css)
assert 'base64' not in css.replace('data:image/svg+xml','KEEP') or True
leftover = re.findall(r'data:(?!image/svg\+xml)[a-z/+.-]+;base64', css)
print('leftover base64 in css:', leftover)
open('src/styles.css', 'w', encoding='utf-8').write(css)

# --- JS ---
js = html[html.rindex('<script>')+8 : html.rindex('</script>')]
open('qa/app-orig.js', 'w', encoding='utf-8').write(js)
print('js bytes:', len(js))

# --- body (for reference while assembling index.html) ---
body = html[html.index('<body>') : html.index('</body>')+7]
body = re.sub(r'data:[a-zA-Z0-9/+.-]+;base64,[A-Za-z0-9+/=]+', 'DATA_URI', body)
open('qa/body-skeleton.html', 'w', encoding='utf-8').write(body)
print('body skeleton bytes:', len(body))
