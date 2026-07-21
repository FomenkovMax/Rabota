import re, base64, io, os
from PIL import Image

html = open('reference/lift-6-updated.html', encoding='utf-8').read()

# ordered names for the 29 base64 data URIs (fonts first, then images in document order)
names = [
    # fonts (order of @font-face blocks)
    'fonts/jetbrains-mono-400-600-cyrillic-ext.woff2',
    'fonts/jetbrains-mono-400-600-cyrillic.woff2',
    'fonts/jetbrains-mono-400-600-latin.woff2',
    'fonts/oswald-500-700-cyrillic-ext.woff2',
    'fonts/oswald-500-700-cyrillic.woff2',
    'fonts/oswald-500-700-latin.woff2',
    'fonts/pt-serif-italic-400-cyrillic-ext.woff2',
    'fonts/pt-serif-italic-400-cyrillic.woff2',
    'fonts/pt-serif-italic-400-latin.woff2',
    'fonts/pt-serif-400-cyrillic-ext.woff2',
    'fonts/pt-serif-400-cyrillic.woff2',
    'fonts/pt-serif-400-latin.woff2',
    'fonts/pt-serif-700-cyrillic-ext.woff2',
    'fonts/pt-serif-700-cyrillic.woff2',
    'fonts/pt-serif-700-latin.woff2',
    # images, document order
    'img/hero-visual-bg.webp',      # css .hero-visual (webp)
    'img/scene-lobby.webp',         # jpeg -> webp
    'img/scene-cabin.webp',         # jpeg -> webp
    'img/scene-top.webp',           # jpeg -> webp
    'img/icon-floor-01.webp',
    'img/icon-floor-02.webp',
    'img/icon-floor-03.webp',
    'img/icon-floor-04.webp',
    'img/icon-floor-05.webp',
    'img/mentor-illustration.webp',
    'img/icon-floor-06.webp',
    'img/icon-floor-07.webp',
    'img/icon-floor-08.webp',
    'img/icon-floor-09.webp',
]

pat = re.compile(r'data:([a-zA-Z0-9/+.-]+);base64,([A-Za-z0-9+/=]+)')
matches = list(pat.finditer(html))
assert len(matches) == len(names), f'{len(matches)} uris vs {len(names)} names'

report = []
for m, name in zip(matches, names):
    mime, b64 = m.group(1), m.group(2)
    raw = base64.b64decode(b64)
    out = os.path.join('src/assets', name)
    if mime == 'image/jpeg':
        img = Image.open(io.BytesIO(raw)).convert('RGB')
        img.save(out, 'WEBP', quality=78, method=6)
        report.append(f'{name}: jpeg {len(raw)} -> webp {os.path.getsize(out)} {img.size[0]}x{img.size[1]}')
    else:
        open(out, 'wb').write(raw)
        if name.endswith('.webp'):
            img = Image.open(io.BytesIO(raw))
            report.append(f'{name}: {len(raw)} bytes {img.size[0]}x{img.size[1]}')
        else:
            report.append(f'{name}: {len(raw)} bytes')
print('\n'.join(report))
