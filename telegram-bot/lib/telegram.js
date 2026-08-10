// Тонкая обёртка над Telegram Bot API: только то, что нужно боту.

const TOKEN = process.env.TELEGRAM_BOT_TOKEN || '';
// Базовый адрес вынесен в переменную окружения, чтобы бота можно было прогнать на моке.
const BASE = process.env.TELEGRAM_API_BASE || 'https://api.telegram.org';
const API = `${BASE}/bot${TOKEN}`;
const FILES = `${BASE}/file/bot${TOKEN}`;
const MAX_MESSAGE = 4000; // у Telegram лимит 4096, оставляем запас на разметку

export const hasToken = () => Boolean(TOKEN);

async function call(method, payload) {
  const response = await fetch(`${API}/${method}`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(payload),
  });
  const json = await response.json().catch(() => ({}));
  if (!json.ok) {
    throw new Error(`Telegram ${method}: ${json.description || response.status}`);
  }
  return json.result;
}

/** Экранирование под parse_mode: HTML. */
export const esc = (value) =>
  String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');

/** Длинный текст режется по абзацам, чтобы не упереться в лимит сообщения. */
export async function sendMessage(chatId, html, extra = {}) {
  const chunks = [];
  let current = '';
  for (const part of String(html).split('\n\n')) {
    if ((current + '\n\n' + part).length > MAX_MESSAGE && current) {
      chunks.push(current);
      current = part;
    } else {
      current = current ? `${current}\n\n${part}` : part;
    }
  }
  if (current) chunks.push(current);

  const sent = [];
  for (const chunk of chunks) {
    sent.push(
      await call('sendMessage', {
        chat_id: chatId,
        text: chunk,
        parse_mode: 'HTML',
        link_preview_options: { is_disabled: true },
        ...extra,
      }),
    );
  }
  return sent;
}

export const sendChatAction = (chatId, action = 'typing') =>
  call('sendChatAction', { chat_id: chatId, action }).catch(() => {});

export const editMessageText = (chatId, messageId, html) =>
  call('editMessageText', { chat_id: chatId, message_id: messageId, text: html, parse_mode: 'HTML' }).catch(
    () => {},
  );

export const deleteMessage = (chatId, messageId) =>
  call('deleteMessage', { chat_id: chatId, message_id: messageId }).catch(() => {});

/** Скачивает фото из Telegram и возвращает его в base64. */
export async function downloadPhoto(fileId) {
  const file = await call('getFile', { file_id: fileId });
  const response = await fetch(`${FILES}/${file.file_path}`);
  if (!response.ok) throw new Error(`Не удалось скачать фото: HTTP ${response.status}`);
  const buffer = Buffer.from(await response.arrayBuffer());
  const ext = (file.file_path.split('.').pop() || 'jpg').toLowerCase();
  const mediaType = ext === 'png' ? 'image/png' : ext === 'webp' ? 'image/webp' : 'image/jpeg';
  return { media_type: mediaType, data: buffer.toString('base64'), bytes: buffer.length };
}

export const setWebhook = (url, secret) =>
  call('setWebhook', {
    url,
    secret_token: secret,
    allowed_updates: ['message'],
    drop_pending_updates: true,
  });

export const getMe = () => call('getMe');
