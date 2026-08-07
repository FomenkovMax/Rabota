// Бесплатная альтернатива Claude: OpenRouter.
// Один ключ (https://openrouter.ai/keys) даёт доступ к моделям разных компаний,
// часть из них бесплатна — их id заканчивается на «:free».
//
// API совместим с OpenAI: POST /chat/completions, картинки передаются
// как data-URL в content-части типа image_url.

const BASE = process.env.OPENROUTER_BASE_URL || 'https://openrouter.ai/api/v1';
const TIMEOUT_MS = Number(process.env.FRIDGE_TIMEOUT_MS || 240_000);
const MAX_TOKENS = Number(process.env.FRIDGE_MAX_TOKENS || 16000);

// Подставляется, если список моделей недоступен: id проверяется живым запросом,
// поэтому ошибиться здесь не страшно — приложение подскажет выбрать другую.
export const FALLBACK_MODEL = 'meta-llama/llama-4-maverick:free';

export class OpenRouterError extends Error {
  constructor(message, status = 502, code = 'openrouter', detail = '') {
    super(message);
    this.status = status;
    this.code = code;
    this.detail = detail; // сырой текст ответа сервера — пригодится для диагностики
  }
}

async function request(path, { key, method = 'GET', body, baseUrl = BASE } = {}) {
  const headers = {
    Authorization: `Bearer ${key}`,
    'content-type': 'application/json',
    // OpenRouter просит указывать приложение — это влияет только на статистику.
    'HTTP-Referer': 'https://github.com/FomenkovMax/Rabota',
    'X-Title': 'Fridge calorie counter',
  };

  let response;
  try {
    response = await fetch(`${baseUrl}${path}`, {
      method,
      headers,
      body: body ? JSON.stringify(body) : undefined,
      signal: AbortSignal.timeout(TIMEOUT_MS),
    });
  } catch (err) {
    if (err?.name === 'TimeoutError') {
      throw new OpenRouterError(
        'Модель не ответила вовремя. Бесплатные модели бывают перегружены — попробуйте ещё раз или выберите другую.',
        504,
        'timeout',
      );
    }
    throw new OpenRouterError(`Нет связи с сервисом (${baseUrl}): ${err?.message || err}`, 502, 'network');
  }

  const text = await response.text();
  let json = null;
  try {
    json = text ? JSON.parse(text) : null;
  } catch {
    /* при инфраструктурных сбоях приходит не-JSON */
  }

  if (!response.ok || json?.error) {
    const detail = json?.error?.message || json?.error || text.slice(0, 300) || `HTTP ${response.status}`;
    const status = response.status || json?.error?.code || 502;
    // Такой текст приходит не от самого OpenRouter, а от того, кто перехватил
    // запрос по дороге: провайдер, антивирус, корпоративный прокси или защита
    // сервиса по региону. Ключ тут ни при чём.
    if (/security policy|access denied|blocked|доступ (?:закрыт|запрещ)/i.test(String(detail))) {
      throw new OpenRouterError(
        `Запрос до OpenRouter не дошёл — его отклонила сеть (HTTP ${status}, «${detail}»). ` +
          'Дело не в ключе. Обычно помогает VPN; ещё стоит проверить антивирус с проверкой HTTPS ' +
          'и настройки сети, если компьютер рабочий.',
        502,
        'blocked',
        `HTTP ${status}, «${detail}»`,
      );
    }
    if (status === 401 || status === 403) {
      throw new OpenRouterError(
        `Ключ OpenRouter не принят. Ответ сервера: HTTP ${status}, «${detail}»`,
        502,
        'auth',
        `HTTP ${status}, «${detail}»`,
      );
    }
    if (status === 402) {
      throw new OpenRouterError(
        'У выбранной модели закончился бесплатный лимит. Выберите другую бесплатную модель в настройках.',
        402,
        'quota',
      );
    }
    if (status === 429) {
      throw new OpenRouterError(
        'Слишком часто или исчерпан дневной бесплатный лимит. Подождите несколько минут и повторите.',
        429,
        'quota',
      );
    }
    if (status === 404) {
      const dataPolicy = /data policy|no endpoints/i.test(detail)
        ? ' Похоже, в аккаунте не разрешены бесплатные модели: откройте openrouter.ai/settings/privacy и включите доступ к ним.'
        : '';
      throw new OpenRouterError(
        `Модель недоступна для этого ключа — выберите другую в настройках.${dataPolicy} Ответ сервера: «${detail}»`,
        404,
        'no_model',
      );
    }
    throw new OpenRouterError(`OpenRouter вернул ошибку: ${detail}`, 502, 'upstream');
  }
  return json ?? {};
}

const isFree = (model) =>
  String(model.id || '').endsWith(':free') ||
  (Number(model.pricing?.prompt) === 0 && Number(model.pricing?.completion) === 0);

const seesImages = (model) => {
  const modalities = model.architecture?.input_modalities || model.architecture?.modality || [];
  const list = Array.isArray(modalities) ? modalities : [String(modalities)];
  return list.some((m) => /image/i.test(m));
};

/** Бесплатные модели, которые умеют смотреть на картинки, — от больших к маленьким. */
export async function listFreeVisionModels(key, baseUrl = BASE) {
  const json = await request('/models', { key, baseUrl });
  return (json.data || [])
    .filter((m) => isFree(m) && seesImages(m))
    .map((m) => ({
      id: m.id,
      name: m.name || m.id,
      context: Number(m.context_length || m.top_provider?.context_length || 0),
    }))
    .sort((a, b) => b.context - a.context);
}

/** Все модели сервиса — для своего адреса, где нет деления на платные и бесплатные. */
export async function listModels(key, baseUrl = BASE) {
  const json = await request('/models', { key, baseUrl });
  return (json.data || json.models || []).map((m) => ({ id: m.id || m.name, name: m.name || m.id }));
}

export function pickModel(models) {
  return models[0]?.id || FALLBACK_MODEL;
}

/**
 * Проверка ключа настоящим запросом в одну лексему: служебный эндпоинт /key
 * отвечает не на все типы ключей, а этот путь проверяет ровно то, что нужно —
 * что ключом можно пользоваться для выбранной модели.
 */
export async function verifyKey(key, model, baseUrl = BASE) {
  try {
    await request('/chat/completions', {
      key,
      baseUrl,
      method: 'POST',
      body: { model, max_tokens: 1, messages: [{ role: 'user', content: 'ping' }] },
    });
    return { ok: true };
  } catch (err) {
    // Ключ рабочий, просто модель сейчас недоступна или упёрлись в лимит.
    if (err.code === 'quota') return { ok: true, warning: err.message };
    if (err.code === 'no_model') {
      return { ok: true, warning: `${err.message} Ключ при этом рабочий.` };
    }
    // Отказ мог прийти из-за модели, а не из-за ключа: спрашиваем баланс, этот
    // запрос не зависит от выбранной модели.
    if (err.code === 'auth') {
      try {
        await request('/credits', { key, baseUrl });
        return {
          ok: true,
          warning: `Ключ рабочий, но модель ${model} его не приняла — выберите другую в списке. Ответ сервера: ${err.detail || err.message}`,
        };
      } catch {
        throw err;
      }
    }
    throw err;
  }
}

/** Один разбор: системный промпт + фото + инструкция → текст ответа (ожидается JSON). */
export async function generate({ key, model, system, prompt, images, baseUrl = BASE }) {
  const content = [
    ...images.map((image) => ({
      type: 'image_url',
      image_url: { url: `data:${image.media_type};base64,${image.data}` },
    })),
    { type: 'text', text: prompt },
  ];

  const body = {
    model,
    max_tokens: MAX_TOKENS,
    messages: [
      { role: 'system', content: system },
      { role: 'user', content },
    ],
    response_format: { type: 'json_object' },
  };

  let json;
  try {
    json = await request('/chat/completions', { key, baseUrl, method: 'POST', body });
  } catch (err) {
    // Не все бесплатные модели понимают response_format — повторяем без него.
    if (err.code === 'upstream' && /response_format|json/i.test(err.message)) {
      delete body.response_format;
      json = await request('/chat/completions', { key, baseUrl, method: 'POST', body });
    } else {
      throw err;
    }
  }

  const choice = json.choices?.[0];
  const text = choice?.message?.content;
  if (!text) {
    if (choice?.finish_reason === 'length') {
      throw new OpenRouterError(
        'Ответ не поместился в лимит модели. Уменьшите число блюд в настройках.',
        502,
        'truncated',
      );
    }
    throw new OpenRouterError('Модель вернула пустой ответ. Попробуйте другую модель.', 502, 'bad_model_output');
  }
  return typeof text === 'string' ? text : text.map((part) => part?.text || '').join('');
}
