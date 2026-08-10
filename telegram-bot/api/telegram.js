// Вебхук Telegram: принимает обновления, разбирает фото, отвечает разбором.
//
// Telegram ждёт ответ на вебхук за секунды, а разбор фото идёт десятки секунд,
// поэтому отвечаем 200 сразу, а работу продолжаем через waitUntil.

import { waitUntil } from '@vercel/functions';
import { analyzePhotos, AnalyzeError, provider } from '../lib/analyze.js';
import { sendMessage, sendChatAction, downloadPhoto, editMessageText, deleteMessage, esc } from '../lib/telegram.js';
import { formatProducts, formatDish, formatFooter, WELCOME } from '../lib/format.js';

const MAX_PHOTOS = 4;
const ALBUM_WAIT_MS = 3000;
const MAX_PHOTO_BYTES = 1_500_000; // берём вариант поменьше: он быстрее и дешевле

// Фото из альбома приходят разными обновлениями — копим их по media_group_id.
const albums = new Map();
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/** Выбирает вариант фото: самый крупный из умеренных по весу. */
function pickPhoto(sizes) {
  const sorted = [...sizes].sort((a, b) => (a.file_size || 0) - (b.file_size || 0));
  const fit = sorted.filter((s) => (s.file_size || 0) <= MAX_PHOTO_BYTES);
  return (fit.length ? fit.at(-1) : sorted[0]).file_id;
}

async function analyzeAndReply(chatId, fileIds, wishes) {
  await sendChatAction(chatId, 'typing');
  const [notice] = await sendMessage(
    chatId,
    `🔍 Смотрю на ${fileIds.length > 1 ? `${fileIds.length} фото` : 'фото'}, считаю калории и подбираю блюда…`,
  );

  try {
    const images = [];
    for (const fileId of fileIds.slice(0, MAX_PHOTOS)) {
      images.push(await downloadPhoto(fileId));
    }

    const result = await analyzePhotos(images, wishes);
    await deleteMessage(chatId, notice.message_id);

    await sendMessage(chatId, formatProducts(result));
    if (result.dishes.length) {
      await sendMessage(chatId, '🍳 <b>Что можно приготовить</b>');
      for (const [i, dish] of result.dishes.entries()) {
        await sendChatAction(chatId, 'typing');
        await sendMessage(chatId, formatDish(dish, i + 1));
      }
    }
    await sendMessage(chatId, formatFooter(result));
  } catch (err) {
    const text =
      err instanceof AnalyzeError
        ? `😕 ${esc(err.message)}`
        : `😕 Не получилось разобрать фото: ${esc(err?.message || err)}`;
    await editMessageText(chatId, notice.message_id, text);
  }
}

async function handlePhoto(message) {
  const chatId = message.chat.id;
  const fileId = pickPhoto(message.photo);
  const caption = (message.caption || '').trim().slice(0, 500);
  const groupId = message.media_group_id;

  if (!groupId) return analyzeAndReply(chatId, [fileId], caption);

  // Первое фото альбома ждёт остальные и отвечает за всех.
  const existing = albums.get(groupId);
  if (existing) {
    existing.fileIds.push(fileId);
    if (caption) existing.caption = caption;
    return;
  }
  const entry = { fileIds: [fileId], caption };
  albums.set(groupId, entry);
  await sleep(ALBUM_WAIT_MS);
  albums.delete(groupId);
  return analyzeAndReply(chatId, entry.fileIds, entry.caption);
}

async function handleUpdate(update) {
  const message = update?.message;
  if (!message?.chat?.id) return;
  const chatId = message.chat.id;

  if (Array.isArray(message.photo) && message.photo.length) return handlePhoto(message);

  const text = (message.text || '').trim();
  if (/^\/(start|help)/.test(text)) {
    const warning =
      provider() === 'none'
        ? '\n\n⚠️ <b>Бот пока не настроен:</b> владельцу нужно добавить ключ модели в переменные окружения.'
        : '';
    return void (await sendMessage(chatId, WELCOME + warning));
  }
  if (message.document?.mime_type?.startsWith('image/')) {
    return void (await sendMessage(
      chatId,
      'Пришлите снимок именно как фото, а не файлом — так Telegram отдаст его в нужном виде.',
    ));
  }
  return void (await sendMessage(
    chatId,
    'Пришлите фото содержимого холодильника 📸\n\nВ подписи можно добавить пожелания: «на 4 порции», «без мяса», «что-нибудь быстрое».',
  ));
}

export default async function handler(req, res) {
  if (req.method !== 'POST') {
    return res.status(405).json({ ok: false, error: 'Only POST' });
  }
  const secret = process.env.TELEGRAM_SECRET;
  if (secret && req.headers['x-telegram-bot-api-secret-token'] !== secret) {
    return res.status(401).json({ ok: false, error: 'Bad secret' });
  }

  // Telegram считает доставку успешной и не шлёт повторов.
  res.status(200).json({ ok: true });

  waitUntil(
    handleUpdate(req.body).catch((err) => {
      console.error('[update]', err);
    }),
  );
}
