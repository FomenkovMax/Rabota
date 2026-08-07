import http from 'node:http';
import os from 'node:os';
import { spawn } from 'node:child_process';
import { createReadStream } from 'node:fs';
import { stat } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import {
  analyze,
  AnalyzeError,
  MAX_IMAGES,
  MEALS,
  DIETS,
  hasCredentials,
  checkAccess,
  resetClient,
} from './src/analyze.js';
import {
  getModel,
  getEffort,
  getProvider,
  getApiKey,
  getOpenRouterKey,
  getOpenRouterModel,
  activeModel,
  keySource,
  saveSettings,
  validateKey,
  PROVIDERS,
  MODEL_CHOICES,
  EFFORT_CHOICES,
  settingsFile,
} from './src/settings.js';
import { demoResult } from './src/demo.js';

const ROOT = path.dirname(fileURLToPath(import.meta.url));
const PUBLIC_DIR = path.join(ROOT, 'public');
const START_PORT = Number(process.env.PORT || 5180);
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

// Ключ можно менять только с самой машины, даже если сервер виден в локальной сети.
const isLocal = (req) => {
  const ip = req.socket.remoteAddress || '';
  return ip === '127.0.0.1' || ip === '::1' || ip === '::ffff:127.0.0.1';
};

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

function currentConfig() {
  return {
    provider: getProvider(),
    providers: PROVIDERS,
    model: DEMO ? 'demo' : activeModel(),
    anthropicModel: getModel(),
    openrouterModel: getOpenRouterModel(),
    effort: getEffort(),
    demo: DEMO,
    ready: DEMO || hasCredentials(),
    keySource: DEMO ? 'demo' : keySource(),
    hasKeys: { anthropic: Boolean(getApiKey()), openrouter: Boolean(getOpenRouterKey()) },
    settingsFile,
    maxImages: MAX_IMAGES,
    meals: MEALS,
    diets: DIETS,
    models: MODEL_CHOICES,
    efforts: EFFORT_CHOICES,
  };
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
    sendJson(res, 200, currentConfig());
    return;
  }

  // Сохранение ключа и параметров модели из интерфейса.
  if (url.pathname === '/api/settings') {
    if (req.method !== 'POST') {
      sendJson(res, 405, { error: 'Метод не поддерживается.', code: 'method_not_allowed' });
      return;
    }
    if (!isLocal(req)) {
      sendJson(res, 403, {
        error: 'Менять ключ можно только на самом компьютере, где запущено приложение.',
        code: 'not_local',
      });
      return;
    }
    try {
      const body = (await readBody(req)) || {};
      const keyProblem =
        (typeof body.apiKey === 'string' ? validateKey(body.apiKey.trim(), 'anthropic') : null) ||
        (typeof body.openrouterKey === 'string'
          ? validateKey(body.openrouterKey.trim(), 'openrouter')
          : null);
      if (keyProblem) {
        sendJson(res, 400, { error: keyProblem, code: 'bad_key' });
        return;
      }
      saveSettings(body);
      resetClient();
      const check = DEMO ? { ok: true, model: 'demo' } : await checkAccess();
      sendJson(res, 200, { ...currentConfig(), check });
    } catch (err) {
      if (err instanceof AnalyzeError) sendJson(res, err.status, { error: err.message, code: err.code });
      else sendJson(res, 500, { error: 'Не удалось сохранить настройки.', code: 'internal' });
    }
    return;
  }

  if (url.pathname === '/api/check') {
    if (!isLocal(req)) {
      sendJson(res, 403, { error: 'Доступно только на самом компьютере.', code: 'not_local' });
      return;
    }
    sendJson(res, 200, DEMO ? { ok: true, model: 'demo' } : await checkAccess());
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

/** Занятый порт — не повод падать: пробуем следующие. */
function listen(port, attemptsLeft = 15) {
  server.once('error', (err) => {
    if (err.code === 'EADDRINUSE' && attemptsLeft > 0) {
      listen(port + 1, attemptsLeft - 1);
    } else {
      console.error('Не удалось запустить сервер:', err.message);
      process.exit(1);
    }
  });
  server.listen(port, HOST, () => onReady(port));
}

function lanAddress() {
  if (HOST !== '0.0.0.0' && HOST !== '::') return null;
  for (const list of Object.values(os.networkInterfaces())) {
    for (const net of list || []) {
      if (net.family === 'IPv4' && !net.internal) return net.address;
    }
  }
  return null;
}

function openBrowser(url) {
  if (process.env.FRIDGE_NO_OPEN === '1') return;
  const [cmd, args] =
    process.platform === 'darwin'
      ? ['open', [url]]
      : process.platform === 'win32'
        ? ['cmd', ['/c', 'start', '', url]]
        : ['xdg-open', [url]];
  try {
    spawn(cmd, args, { stdio: 'ignore', detached: true }).unref();
  } catch {
    /* нет графической оболочки — просто откроют ссылку руками */
  }
}

function onReady(port) {
  const local = `http://localhost:${port}`;
  const lan = lanAddress();
  console.log('');
  console.log('  Что приготовить — счётчик калорий по фото холодильника');
  console.log('  ────────────────────────────────────────────────────');
  console.log(`  Откройте в браузере:  ${local}`);
  if (lan) console.log(`  С телефона в той же сети:  http://${lan}:${port}`);
  console.log(DEMO ? '  Режим: демо (модель не вызывается)' : `  Модель: ${getModel()} (${getEffort()})`);
  if (!DEMO && !hasCredentials()) {
    console.log('  Ключ API пока не задан — вставьте его на странице, в блоке «Настройка доступа».');
  }
  console.log('');
  console.log('  Чтобы остановить: закройте это окно или нажмите Ctrl+C');
  console.log('');
  openBrowser(local);
}

listen(START_PORT);
