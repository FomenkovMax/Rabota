// Открывается в браузере один раз после деплоя: регистрирует вебхук в Telegram
// и показывает, что настроено, а что нет. Никакого терминала не нужно.

import { setWebhook, getMe, hasToken } from '../lib/telegram.js';
import { provider, activeModel } from '../lib/analyze.js';

const page = (title, rows, ok) => `<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>${title}</title><style>
body{margin:0;padding:32px 16px;background:#0e1113;color:#e8edf0;font:16px/1.55 -apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif}
main{max-width:640px;margin:0 auto}
h1{font-size:22px;margin:0 0 6px}
p{color:#98a4ac;margin:0 0 20px}
ul{list-style:none;padding:0;margin:0 0 24px}
li{padding:12px 14px;border:1px solid #2b3237;border-radius:12px;margin-bottom:8px;background:#171b1e}
b{color:#e8edf0}
code{background:#1f2529;padding:2px 6px;border-radius:6px;font-size:14px}
.ok{color:#7ad07f}.bad{color:#e2685f}
a{color:#7ad07f}
</style></head><body><main>
<h1>${ok ? '✅' : '⚠️'} ${title}</h1>
<p>Счётчик калорий по фото холодильника — настройка бота</p>
<ul>${rows.map((r) => `<li>${r}</li>`).join('')}</ul>
</main></body></html>`;

export default async function handler(req, res) {
  const rows = [];
  let ok = true;

  if (!hasToken()) {
    res.setHeader('content-type', 'text/html; charset=utf-8');
    return res
      .status(200)
      .send(
        page(
          'Не хватает токена бота',
          [
            'В переменных окружения проекта нет <code>TELEGRAM_BOT_TOKEN</code>.',
            'Добавьте его в настройках проекта на Vercel (Settings → Environment Variables), сделайте Redeploy и откройте эту страницу снова.',
          ],
          false,
        ),
      );
  }

  try {
    const me = await getMe();
    rows.push(`<b class="ok">Бот найден:</b> @${me.username}`);
  } catch (err) {
    ok = false;
    rows.push(`<b class="bad">Токен не принят:</b> ${err.message}`);
  }

  const which = provider();
  if (which === 'none') {
    ok = false;
    rows.push(
      '<b class="bad">Нет ключа модели.</b> Добавьте <code>OPENROUTER_API_KEY</code> (бесплатные модели) ' +
        'или <code>ANTHROPIC_API_KEY</code> (Claude, платно) в переменные окружения и сделайте Redeploy.',
    );
  } else {
    rows.push(`<b class="ok">Модель:</b> ${activeModel()} (${which})`);
  }

  if (ok) {
    const host = req.headers['x-forwarded-host'] || req.headers.host;
    const url = `https://${host}/api/telegram`;
    try {
      await setWebhook(url, process.env.TELEGRAM_SECRET || undefined);
      rows.push(`<b class="ok">Вебхук подключён:</b> <code>${url}</code>`);
      rows.push('Готово — открывайте бота в Telegram и присылайте фото холодильника 📸');
    } catch (err) {
      ok = false;
      rows.push(`<b class="bad">Не удалось подключить вебхук:</b> ${err.message}`);
    }
  }

  res.setHeader('content-type', 'text/html; charset=utf-8');
  res.status(200).send(page(ok ? 'Бот настроен' : 'Настройка не завершена', rows, ok));
}
