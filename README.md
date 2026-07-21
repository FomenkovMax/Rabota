# ЛИФТ — лендинг проекта кадрового резерва

Продакшен-версия арт-концепта `reference/lift-6-updated.html` (тёмный ink + латунь,
ар-деко, scroll-linked анимации). Дизайн, тексты и структура — без изменений;
монолитный 2-мегабайтный HTML разобран на ассеты и собирается Vite.

## Команды

```bash
npm install        # зависимости (Vite)
npm run dev        # дев-сервер с HMR — http://localhost:5173
npm run build      # продакшен-сборка в dist/
npm run preview    # локальный просмотр dist/ — http://localhost:4173
```

## Структура

```
index.html            разметка (семантика: header/main/section/footer, SEO, schema.org)
src/styles.css        весь CSS; маркер /*! CRITICAL-END */ делит его на критическую
                      и отложенную части (см. «Сборка»)
src/app.js            логика этажей (IntersectionObserver, HUD, рельса, маршрут)
src/assets/fonts/     woff2-сабсеты (latin → ASCII+пунктуация, cyrillic — как в Google Fonts)
src/assets/img/       webp-изображения и concierge.svg
public/               favicon, apple-touch-icon, og-image.jpg, robots.txt
qa/                   скрипты проверки (скриншоты, дифф, вес, a11y) и отчёт Lighthouse
reference/            исходный монолит — эталон для визуальной регрессии
```

## Сборка

- Кастомный Vite-плагин (`vite.config.js`) инлайнит критическую часть CSS в `<head>`,
  остальное грузится асинхронно (`preload` + `onload`, с `noscript`-фолбэком).
- Хэши в именах файлов; `assetsInlineLimit: 2048` — data-URI больше 2 КБ не инлайнятся.
- Фоны cabin/top подключаются из JS лениво (idle/scroll) — первый экран платит
  только за сцену лобби.
- JPEG-сцены пережаты в WebP (q62–68) — они лежат за тёмным скримом, разница не видна.
- Латинские сабсеты шрифтов урезаны до ASCII + типографской пунктуации; блоки
  cyrillic-ext удалены (на странице нет расширенной кириллицы). При добавлении
  текста с диакритикой/казахской кириллицей верните полные файлы из исходника.

## Бюджеты (замер: `node qa/weigh.cjs`)

- `dist/index.html` — 35 КБ (< 50 КБ).
- Первый экран: ~277 КБ по сети (brotli), ~356 КБ без сжатия.
- Lighthouse (см. `qa/lighthouse.report.html`): Performance 97, Accessibility 96,
  Best Practices 100, SEO 100.

## Деплой (Netlify)

`netlify.toml`: сборка `npm run build`, публикация `dist/`, для `/assets/*` —
`Cache-Control: immutable, max-age=31536000`.

После привязки домена замените относительный `og:image` (`/og-image.jpg`) на
абсолютный URL в `index.html` — часть скраперов не понимает относительные пути.

## Проверка регрессий

```bash
npm run build && npm run preview &
node qa/shot.cjs http://localhost:4173/ qa/screens/new   # скриншоты 1440×900 и 390×844
python3 qa/diff.py                                       # пиксельный дифф с эталоном
node qa/weigh.cjs                                        # вес первого экрана
node qa/a11y.cjs                                         # клавиатура + reduced-motion
```

Эталонные скриншоты снимаются с `reference/lift-6-updated.html`. Высоты страниц
должны совпадать точно (9772px десктоп / 10488px мобайл); допустимая разница
пикселей — только от пережатия изображений.
