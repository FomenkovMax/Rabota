# -*- coding: utf-8 -*-
# Собирает автономный одиночный HTML: все шрифты/картинки/CSS/JS вшиты data-URI.
import base64, re, os

def data_uri(path, mime):
    return f'data:{mime};base64,' + base64.b64encode(open(path,'rb').read()).decode()

MIME = {'.woff2':'font/woff2', '.webp':'image/webp', '.svg':'image/svg+xml', '.png':'image/png', '.jpg':'image/jpeg'}
def uri_for(rel):
    p = os.path.join('src', rel) if not rel.startswith(('src/','public/')) else rel
    return data_uri(p, MIME[os.path.splitext(p)[1]])

css = open('src/styles.css', encoding='utf-8').read()
css = css.replace('/*! CRITICAL-END */', '')
css = re.sub(r"url\('\./assets/([^']+)'\)", lambda m: "url('" + uri_for('assets/' + m.group(1)) + "')", css)

js = open('src/app.js', encoding='utf-8').read()
js = js.replace("import './styles.css';\n", '')
js = js.replace("import sceneCabinUrl from './assets/img/scene-cabin.webp';",
                "var sceneCabinUrl = '" + uri_for('assets/img/scene-cabin.webp') + "';")
js = js.replace("import sceneTopUrl from './assets/img/scene-top.webp';",
                "var sceneTopUrl = '" + uri_for('assets/img/scene-top.webp') + "';")

html = open('index.html', encoding='utf-8').read()
html = re.sub(r'<img([^>]*?)src="\./src/assets/img/([^"]+)"',
              lambda m: '<img' + m.group(1) + 'src="' + uri_for('assets/img/' + m.group(2)) + '"', html)
# preload-ссылки не нужны, всё уже внутри файла
html = re.sub(r'<link rel="preload" as="image"[^>]*>\n?', '', html)
html = html.replace('<link rel="icon" href="/favicon.png" type="image/png" sizes="48x48">',
                    f'<link rel="icon" href="{data_uri("public/favicon.png","image/png")}" type="image/png" sizes="48x48">')
html = html.replace('<link rel="apple-touch-icon" href="/apple-touch-icon.png">', '')
html = html.replace('<script type="module" src="/src/app.js"></script>',
                    '<style>\n' + css + '</style>')
html = html.replace('</body>', '<script>\n' + js + '\n</script>\n</body>')
out = '/tmp/claude-0/-home-user/a2633d04-e622-5930-994b-fa25264a22db/scratchpad/lift-landing-standalone.html'
open(out, 'w', encoding='utf-8').write(html)
print('standalone:', os.path.getsize(out), 'bytes')
assert 'src="./src/' not in html and "url('./assets" not in html
