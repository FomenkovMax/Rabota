# Спецификация ассетов (v1)

Код ссылается на ассеты **по ID**: файл кладётся в `webapp/public/assets/<ID>.<ext>`, правок кода не нужно.
Пока файла нет, компонент `Asset` показывает запасной эмодзи. Генерация в Higgsfield — только после отдельного «да» со сметой.

Общий стиль: тёмная ТВ-студия, глубокий синий + тёплое золото, мягкий свет, без текста на картинках, единая модель и референс-кадр для всех.

| ID | Экран | Тип | Размер / формат | Длительность | Промпт (EN) | Путь |
|---|---|---|---|---|---|---|
| `home.logo` | Главная | картинка, прозрачный фон | 512×512 webp | — | Wise golden owl emblem, studio spotlight, deep navy and gold, centered, transparent background, no text | `webapp/public/assets/home.logo.webp` |
| `bg.studio` | Все экраны | фон | 1080×1920 webp | — | Dark game-show studio, deep blue gradient, soft gold light beams, empty, vertical | `…/bg.studio.webp` |
| `wheel.table` | Волчок (Э2–Э3) | картинка | 1024×1024 webp | — | Top view of a round game table with 13 sectors, dark blue and gold, no text | `…/wheel.table.webp` |
| `wheel.arrow` | Волчок | слой, прозрачный фон | 512×512 webp | — | Golden spinning arrow pointer, top view, transparent background | `…/wheel.arrow.webp` |
| `wheel.envelope.closed` | Волчок | иконка | 512×512 webp | — | Closed cream envelope with gold seal, transparent background | `…/wheel.envelope.closed.webp` |
| `wheel.envelope.open` | Волчок | иконка | 512×512 webp | — | Open envelope with a card sliding out, transparent background | `…/wheel.envelope.open.webp` |
| `award.owl` | Награды (Э5) | картинка | 512×512 webp | — | Golden owl trophy, studio light, transparent background | `…/award.owl.webp` |
| `award.owl.diamond` | Награды | картинка | 512×512 webp | — | Diamond crystal owl trophy, sparkling, transparent background | `…/award.owl.diamond.webp` |
| `award.ceremony` | Награды | видео | 720×1280 mp4 | ~6 с | Owl trophy rising on a stage in golden light, confetti, slow camera push-in | `…/award.ceremony.mp4` |
| `result.win` | Итог | картинка | 768×768 webp | — | Triumphant golden light burst, confetti, no text | `…/result.win.webp` |
| `result.lose` | Итог | картинка | 768×768 webp | — | Calm dim blue light, single falling feather, no text | `…/result.lose.webp` |
| `loader` | Загрузка | картинка | 256×256 webp | — | Small golden owl, wings spread, transparent background | `…/loader.webp` |
| `ach.*` | Ачивки (Э5) | иконки | 256×256 webp | — | Round gold-rimmed badge icon with a simple symbol (по списку ачивок) | `…/ach.<имя>.webp` |
| `sfx.spin` `sfx.tick` `sfx.timer10` `sfx.ok` `sfx.fail` | Звуки (Э3) | аудио | mp3 | 0.3–3 с | wheel spin, click, 10-second timer pulse, success chime, soft fail | `…/sfx.<имя>.mp3` |

## Правила
- Картинки оптимизируем в WebP; видео — H.264 mp4, до ~3 МБ.
- Прозрачность для слоёв — через `remove_background`.
- Новый ассет = новая строка в таблице + одноимённый файл.


## Статус (набор 1 готов)
Сделаны (Nano Banana 2 / Pro + вырезание фона, стиль-референс — `art_src/welcome.png`): `home.logo`, `bg.studio`, `wheel.table`, `wheel.arrow`, `wheel.envelope.closed`, `wheel.envelope.open`, `award.owl`, `award.owl.diamond`, `result.win`, `result.lose`, `loader`.
Осталось: `ach.*` (набор 2), `award.ceremony.mp4` (набор 3), звуки `sfx.*` (Higgsfield не делает отдельные SFX — берём CC0).
Примечания: у стола `wheel.table` секторов нарисовано не 13, поэтому сектора и цифры рисует код внутри золотого кольца, а картинка даёт только раму.
