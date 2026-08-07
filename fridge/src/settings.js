// Настройки хранятся в .data/settings.json рядом с приложением, чтобы ключ
// можно было ввести в браузере, а не через переменные окружения.
// Переменные окружения, если заданы, всё равно главнее файла.
import { readFileSync, writeFileSync, mkdirSync, existsSync, chmodSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const DATA_DIR = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', '.data');
const FILE = path.join(DATA_DIR, 'settings.json');

export const PROVIDERS = {
  anthropic: 'Claude — точнее всего, платно',
  openrouter: 'OpenRouter — есть бесплатные модели',
};

export const MODEL_CHOICES = {
  'claude-opus-5': 'Opus 5 — точнее всего',
  'claude-sonnet-5': 'Sonnet 5 — дешевле и быстрее',
  'claude-haiku-4-5': 'Haiku 4.5 — самый дешёвый',
};

export const EFFORT_CHOICES = {
  low: 'быстро и дёшево',
  medium: 'сбалансированно',
  high: 'тщательно (по умолчанию)',
  xhigh: 'очень тщательно',
};

const DEFAULTS = {
  provider: 'anthropic',
  apiKey: '',
  model: 'claude-opus-5',
  effort: 'high',
  openrouterKey: '',
  openrouterModel: '',
};

let cache = null;

function read() {
  if (cache) return cache;
  try {
    cache = { ...DEFAULTS, ...JSON.parse(readFileSync(FILE, 'utf8')) };
  } catch {
    cache = { ...DEFAULTS };
  }
  return cache;
}

export function getSettings() {
  return { ...read() };
}

/** Ключи уходят в HTTP-заголовки, поэтому в них допустимы только печатные ASCII-символы. */
export function validateKey(key, provider = getProvider()) {
  if (!key) return null;
  if (!/^[\x21-\x7e]+$/.test(key)) {
    return 'В ключе есть пробелы или нелатинские символы. Скопируйте его целиком из консоли.';
  }
  if (provider === 'anthropic' && !key.startsWith('sk-ant-')) {
    return 'Ключ Claude должен начинаться с «sk-ant-». Похоже, скопирована не та строка.';
  }
  if (provider === 'openrouter' && !key.startsWith('sk-or-')) {
    return 'Ключ OpenRouter должен начинаться с «sk-or-». Похоже, скопирована не та строка.';
  }
  return null;
}

export function saveSettings(patch) {
  const next = { ...read() };
  if (Object.hasOwn(PROVIDERS, patch.provider)) next.provider = patch.provider;
  if (typeof patch.apiKey === 'string') next.apiKey = patch.apiKey.trim();
  if (typeof patch.openrouterKey === 'string') next.openrouterKey = patch.openrouterKey.trim();
  if (typeof patch.openrouterModel === 'string') next.openrouterModel = patch.openrouterModel.trim();
  if (Object.hasOwn(MODEL_CHOICES, patch.model)) next.model = patch.model;
  if (Object.hasOwn(EFFORT_CHOICES, patch.effort)) next.effort = patch.effort;

  mkdirSync(DATA_DIR, { recursive: true });
  writeFileSync(FILE, JSON.stringify(next, null, 2), { encoding: 'utf8', mode: 0o600 });
  try {
    chmodSync(FILE, 0o600); // на случай, если файл уже существовал с другими правами
  } catch {
    /* Windows — прав всё равно нет */
  }
  cache = next;
  return { ...next };
}

export function getProvider() {
  const fromEnv = process.env.FRIDGE_PROVIDER;
  return Object.hasOwn(PROVIDERS, fromEnv) ? fromEnv : read().provider;
}

/** Откуда взят ключ активного провайдера: окружение, файл настроек или ниоткуда. */
export function keySource() {
  if (getProvider() === 'openrouter') {
    if (process.env.OPENROUTER_API_KEY) return 'env';
    return read().openrouterKey ? 'file' : 'none';
  }
  if (process.env.ANTHROPIC_API_KEY || process.env.ANTHROPIC_AUTH_TOKEN) return 'env';
  return read().apiKey ? 'file' : 'none';
}

export function getApiKey() {
  return process.env.ANTHROPIC_API_KEY || read().apiKey || '';
}

export function getOpenRouterKey() {
  return process.env.OPENROUTER_API_KEY || read().openrouterKey || '';
}

export function getOpenRouterModel() {
  return process.env.OPENROUTER_MODEL || read().openrouterModel || '';
}

export function getModel() {
  return process.env.ANTHROPIC_MODEL || read().model;
}

export function getEffort() {
  return process.env.FRIDGE_EFFORT || read().effort;
}

/** Модель активного провайдера — для показа в интерфейсе. */
export function activeModel() {
  return getProvider() === 'openrouter' ? getOpenRouterModel() || 'подберём автоматически' : getModel();
}

export const settingsFile = FILE;
export const settingsExists = () => existsSync(FILE);
