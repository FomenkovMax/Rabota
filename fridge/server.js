import http from 'node:http';
import { createReadStream } from 'node:fs';
import { stat } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { analyze, AnalyzeError, MAX_IMAGES, MEALS, DIETS, MODEL, hasCredentials } from './src/analyze.js';
import { demoResult } from './src/demo.js';

const ROOT = path.dirname(fileURLToPath(import.meta.url));
const PUBLIC_DIR = path.join(ROOT, 'public');
const PORT = Number(process.env.PORT || 5180);
const HOST = process.env.HOST || '0.0.0.0';
const MAX_BODY = 32 * 1024 * 1024;
const DEMO = process.env.FRIDGE_DEMO === '1';

// Простое ограничение частоты: запросы к модели платные, а сервер обычно
// поднимают на домашней машине без другой защиты.
const RATE_WINDOW_MS = 60_000;
const RATE_LIMIT = Number(process.env.FRIDGE_RATE_LIMIT || 10);
const hits = new Map();

function rateLimited(ip) {
  const now = Date.now();
  const recent = (hits.get(ip) || []).filter((t) => now - t < RATE_WINDOW_MS);
  if (recent.length >= RATE_LIMIT) {
    hits.set(ip, recent);
    return true;
  }
  recent.push(now);
  hits.set(ip, recent);
  if (hits.size > 1000) {
    for (const [key, times] of hits) if (times.every((t) => now - t >= RATE_WINDOW_MS)) hits.delete(key);
  }
  return false;
}

const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
  '.ico': 'image/x-icon',
  '.webmanifest': 'application/manifest+json',
};

function sendJson(res, status, payload) {
  const body = JSON.stringify(payload);
  res.writeHead(status, {
    'content-type': 'application/json; charset=utf-8',
    'content-length': Buffer.byteLength(body),
    'cache-control': 'no-store',
  });
  res.end(body);
}

function readBody(req) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    let size = 0;
    req.on('data', (chunk) => {
      size += chunk.length;
      if (size > MAX_BODY) {
        reject(new AnalyzeError('Запрос слишком большой — уменьшите число или размер фото.', 413, 'too_large'));
        req.destroy();
        return;
      }
      chunks.push(chunk);
    });
    req.on('end', () => {
      try {
        resolve(chunks.length ? JSON.parse(Buffer.concat(chunks).toString('utf8')) : {});
      } catch {
        reject(new AnalyzeError('Тело запроса не является корректным JSON.'));
      }
    });
    req.on('error', reject);
  });
}

async function serveStatic(req, res, pathname) {
  const rel = pathname === '/' ? 'index.html' : decodeURIComponent(pathname).replace(/^\/+/, '');
  const filePath = path.join(PUBLIC_DIR, rel);
  if (!filePath.startsWith(PUBLIC_DIR + path.sep) && filePath !== PUBLIC_DIR) {
    res.writeHead(403).end('Forbidden');
    return;
  }
  try {
    const info = await stat(filePath);
    if (!info.isFile()) throw new Error('not a file');
    res.writeHead(200, {
      'content-type': MIME[path.extname(filePath)] || 'application/octet-stream',
      'content-length': info.size,
      'cache-control': 'no-cache',
    });
    createReadStream(filePath).pipe(res);
  } catch {
    res.writeHead(404, { 'content-type': 'text/plain; charset=utf-8' }).end('404 — страница не найдена');
  }
}

const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, `http://${req.headers.host || 'localhost'}`);

  if (url.pathname === '/api/config') {
    sendJson(res, 200, {
      model: DEMO ? 'demo' : MODEL,
      demo: DEMO,
      ready: DEMO || hasCredentials(),
      maxImages: MAX_IMAGES,
      meals: MEALS,
      diets: DIETS,
    });
    return;
  }

  if (url.pathname === '/api/analyze') {
    if (req.method !== 'POST') {
      sendJson(res, 405, { error: 'Метод не поддерживается.', code: 'method_not_allowed' });
      return;
    }
    const ip = req.socket.remoteAddress || 'unknown';
    if (rateLimited(ip)) {
      sendJson(res, 429, {
        error: `Не больше ${RATE_LIMIT} запросов в минуту. Подождите немного.`,
        code: 'rate_limit',
      });
      return;
    }
    try {
      const body = await readBody(req);
      const result = DEMO ? demoResult(body?.options || {}) : await analyze(body);
      sendJson(res, 200, result);
    } catch (err) {
      if (err instanceof AnalyzeError) {
        sendJson(res, err.status, { error: err.message, code: err.code });
      } else {
        console.error('[analyze]', err);
        sendJson(res, 500, { error: 'Внутренняя ошибка сервера.', code: 'internal' });
      }
    }
    return;
  }

  if (req.method !== 'GET' && req.method !== 'HEAD') {
    res.writeHead(405).end('Method Not Allowed');
    return;
  }
  await serveStatic(req, res, url.pathname);
});

server.listen(PORT, HOST, () => {
  const where = `http://localhost:${PORT}`;
  console.log(`Счётчик калорий по фото холодильника → ${where}`);
  console.log(DEMO ? 'Режим: демо (модель не вызывается)' : `Модель: ${MODEL}`);
  if (!DEMO && !hasCredentials()) {
    console.warn('ANTHROPIC_API_KEY не задан — анализ вернёт ошибку. См. README.md');
  }
});
