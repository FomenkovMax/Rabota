// Netlify Function (v2): тот же анализ, что и в server.js, но без своего сервера.
// Подключается редиректом /api/analyze → /.netlify/functions/analyze (см. netlify.toml).
import { analyze, AnalyzeError } from '../../src/analyze.js';
import { demoResult } from '../../src/demo.js';

const json = (status, payload) =>
  new Response(JSON.stringify(payload), {
    status,
    headers: { 'content-type': 'application/json; charset=utf-8', 'cache-control': 'no-store' },
  });

export default async (req) => {
  if (req.method !== 'POST') {
    return json(405, { error: 'Метод не поддерживается.', code: 'method_not_allowed' });
  }
  try {
    const body = await req.json();
    const result =
      process.env.FRIDGE_DEMO === '1' ? demoResult(body?.options || {}) : await analyze(body);
    return json(200, result);
  } catch (err) {
    if (err instanceof AnalyzeError) return json(err.status, { error: err.message, code: err.code });
    console.error('[analyze]', err);
    return json(500, { error: 'Внутренняя ошибка сервера.', code: 'internal' });
  }
};

export const config = { path: '/api/analyze' };

// Важно: у синхронных функций Netlify жёсткий лимит времени (10–26 с в зависимости
// от плана), а анализ фото на claude-opus-5 с effort=high обычно идёт дольше.
// Для деплоя на Netlify ставьте FRIDGE_EFFORT=low и 3–4 блюда либо разворачивайте
// server.js там, где таймаут не ограничен (VPS, Fly.io, Railway, Render).
