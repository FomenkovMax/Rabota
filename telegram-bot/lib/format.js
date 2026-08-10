// Оформление результата под Telegram: HTML-разметка, отдельное сообщение на блюдо.

import { esc } from './telegram.js';

const num = (n) => Math.round(Number(n) || 0).toLocaleString('ru-RU');

const plural = (n, one, few, many) => {
  const abs = Math.abs(n) % 100;
  const last = abs % 10;
  if (abs > 10 && abs < 20) return many;
  if (last > 1 && last < 5) return few;
  return last === 1 ? one : many;
};

/** Сводка: список продуктов и общая калорийность. */
export function formatProducts(result) {
  const { products, total_kcal: total } = result;
  if (!products.length) {
    return `🤔 Продуктов на фото не разглядел.${result.notes ? `\n\n${esc(result.notes)}` : ''}`;
  }

  const lines = products.map((p) => {
    const doubt = p.confidence === 'низкая' ? ' ⚠️' : '';
    return `• <b>${esc(p.name)}</b>${doubt} — ${esc(p.amount)} · ${num(p.grams)} г · <b>${num(p.kcal)}</b> ккал`;
  });

  return [
    `🧊 <b>В холодильнике: ${products.length} ${plural(products.length, 'продукт', 'продукта', 'продуктов')} на ${num(total)} ккал</b>`,
    '',
    lines.join('\n'),
    '',
    '<i>⚠️ — распознано неуверенно, проверьте сами</i>',
  ].join('\n');
}

/** Карточка блюда: заголовок, КБЖУ, состав, шаги. */
export function formatDish(dish, index) {
  const ps = dish.per_serving || {};
  const badges = [
    dish.ready_now ? '✅ всё есть' : `🛒 докупить: ${esc(dish.missing.join(', '))}`,
    `⏱ ${dish.time_minutes} мин`,
    esc(dish.difficulty),
  ].join(' · ');

  const ingredients = dish.ingredients
    .map((ing) => {
      const mark = ing.available ? '' : ' <i>(нет)</i>';
      return `  · ${esc(ing.product)} — ${esc(ing.amount)}${mark} · ${num(ing.kcal)} ккал`;
    })
    .join('\n');

  const steps = dish.steps.map((step, i) => `  ${i + 1}. ${esc(step)}`).join('\n');

  return [
    `${index}. <b>${esc(dish.name)}</b> — <b>${num(ps.kcal)} ккал</b> на порцию`,
    dish.description ? `<i>${esc(dish.description)}</i>` : '',
    badges,
    `Б ${num(ps.protein_g)} г · Ж ${num(ps.fat_g)} г · У ${num(ps.carbs_g)} г · всего ${num(dish.total?.kcal)} ккал на ${dish.servings} ${plural(dish.servings, 'порцию', 'порции', 'порций')}`,
    '',
    `<b>Состав</b>\n${ingredients}`,
    '',
    `<b>Приготовление</b>\n${steps}`,
  ]
    .filter(Boolean)
    .join('\n');
}

/** Хвост: заметки модели и подпись о том, чем считали. */
export function formatFooter(result) {
  const parts = [];
  if (result.notes) parts.push(`💡 ${esc(result.notes)}`);
  parts.push(
    `<i>Считала модель ${esc(result.meta.model)} за ${Math.round(result.meta.elapsed_ms / 1000)} с. ` +
      'Калорийность оценена по внешнему виду — это ориентир, а не измерение.</i>',
  );
  return parts.join('\n\n');
}

export const WELCOME = [
  '🥗 <b>Что приготовить</b>',
  '',
  'Пришлите фото содержимого холодильника — отвечу, что там лежит, сколько это калорий и что из этого можно приготовить.',
  '',
  '<b>Как пользоваться</b>',
  '• Снимите полки как есть, лучше при хорошем свете',
  '• Можно прислать несколько фото сразу — разберу вместе',
  '• В подписи к фото напишите пожелания: <i>«на 4 порции»</i>, <i>«без мяса»</i>, <i>«что-то быстрое на ужин»</i>',
  '',
  'Команды: /start — это сообщение, /help — то же самое.',
].join('\n');
