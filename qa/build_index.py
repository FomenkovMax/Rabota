# -*- coding: utf-8 -*-
import re

html = open('reference/lift-6-updated.html', encoding='utf-8').read()
body = html[html.index('<body>')+6 : html.index('</body>')]

# 1) concierge svg -> external <img> (same class/intrinsic size)
svg_start = body.index('<svg class="concierge-svg"')
svg_end = body.index('</svg>', body.index('recraft-signature')) + len('</svg>')
img_tag = ('<img class="concierge-svg" src="./src/assets/img/concierge.svg" width="1792" height="2432" '
           'alt="Консьерж открывает решётчатую дверь лифта" fetchpriority="high" decoding="async">')
body = body[:svg_start] + img_tag + body[svg_end:]

# 2) scene layers: strip inline base64 backgrounds
body = re.sub(r'(<div class="scene-layer[^"]*" data-mood="[a-z]+") style="background-image:url\(\'data:[^\']+\'\)"',
              r'\1', body)

# 3) floor icons in document order: 01..05, then 06..09 (mentor img sits between but has a distinct class)
icon_order = ['01','02','03','04','05','06','07','08','09']
idx = iter(icon_order)
def repl_icon(m):
    n = next(idx)
    lazy = '' if n == '01' else ' loading="lazy"'
    return (f'<img class="floor-icon" src="./src/assets/img/icon-floor-{n}.webp" width="256" height="256"'
            f'{lazy} decoding="async" alt="" aria-hidden="true">')
body, count = re.subn(r'<img class="floor-icon" src="data:[^"]+" alt="" aria-hidden="true">', repl_icon, body)
assert count == 9, count

# 4) mentor illustration
body, count = re.subn(
    r'<img class="mentor-illustration" src="data:[^"]+"',
    '<img class="mentor-illustration" src="./src/assets/img/mentor-illustration.webp" width="900" height="506" loading="lazy" decoding="async"',
    body)
assert count == 1, count

# 5) hero <section> -> <header> (semantic; styles are class-based, JS uses [data-floor])
body = body.replace('<section class="hero" data-floor="0" id="floor-0">',
                    '<header class="hero" data-floor="0" id="floor-0">')
# its matching close tag is the first </section> after the hero block
hero_pos = body.index('<header class="hero"')
close_pos = body.index('</section>', hero_pos)
body = body[:close_pos] + '</header>' + body[close_pos+len('</section>'):]

# 6) drop the inline <script> (moves to src/app.js as a module)
body = body[:body.rindex('<script>')].rstrip() + '\n'

assert 'base64' not in body

head = '''<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ЛИФТ — проект кадрового резерва</title>
<meta name="description" content="«Лифт»: прозрачный путь от специалиста до руководителя грейда 12+, показанный как поездка на лифте — этаж за этажом.">
<meta name="theme-color" content="#0b0f10">
<link rel="icon" href="/favicon.png" type="image/png" sizes="48x48">
<link rel="apple-touch-icon" href="/apple-touch-icon.png">
<meta property="og:type" content="website">
<meta property="og:site_name" content="ЛИФТ">
<meta property="og:title" content="ЛИФТ — проект кадрового резерва">
<meta property="og:description" content="Прозрачный путь от специалиста до руководителя грейда 12+ — девять этажей отбора, наставник, практика и аттестация.">
<meta property="og:image" content="/og-image.jpg">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta property="og:locale" content="ru_RU">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="ЛИФТ — проект кадрового резерва">
<meta name="twitter:image" content="/og-image.jpg">
<link rel="preload" as="image" href="./src/assets/img/scene-lobby.webp" fetchpriority="high">
<link rel="preload" as="image" href="./src/assets/img/icon-floor-01.webp">
<script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@type": "WebPage",
  "name": "ЛИФТ — проект кадрового резерва",
  "description": "«Лифт»: прозрачный путь от специалиста до руководителя грейда 12+, показанный как поездка на лифте — этаж за этажом.",
  "inLanguage": "ru"
}
</script>
<script type="module" src="/src/app.js"></script>
</head>
<body>'''

open('index.html', 'w', encoding='utf-8').write(head + body + '</body>\n</html>\n')
import os
print('index.html bytes:', os.path.getsize('index.html'))
