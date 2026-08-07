const MAX_EDGE = 1600; // длинная сторона фото перед отправкой, px
const JPEG_QUALITY = 0.82;
const STORAGE_KEY = 'fridge-options-v1';

const $ = (id) => document.getElementById(id);

const ui = {
  modelBadge: $('model-badge'),
  dropzone: $('dropzone'),
  fileInput: $('file-input'),
  maxImages: $('max-images'),
  thumbs: $('thumbs'),
  analyze: $('analyze'),
  reset: $('reset'),
  status: $('status'),
  error: $('error'),
  errorText: $('error-text'),
  results: $('results'),
  summary: $('summary'),
  productsBody: document.querySelector('#products-table tbody'),
  productsCount: $('products-count'),
  dishes: $('dishes'),
  notes: $('notes'),
  filterReady: $('filter-ready'),
  sortDishes: $('sort-dishes'),
  setup: $('setup'),
  setupState: $('setup-state'),
  setupStatus: $('setup-status'),
  saveSettings: $('save-settings'),
  key: $('opt-key'),
  model: $('opt-model'),
  effort: $('opt-effort'),
  opts: {
    servings: $('opt-servings'),
    maxDishes: $('opt-dishes'),
    meal: $('opt-meal'),
    diet: $('opt-diet'),
    kcalTarget: $('opt-kcal'),
    notes: $('opt-notes'),
    pantry: $('opt-pantry'),
    onlyAvailable: $('opt-only'),
  },
};

const state = {
  images: [],
  maxImages: 4,
  result: null,
  busy: false,
  ready: false,
};

/* ---------- мелкие помощники ---------- */

function h(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (value === null || value === undefined || value === false) continue;
    if (key === 'class') node.className = value;
    else if (key === 'text') node.textContent = value;
    else if (key.startsWith('on')) node.addEventListener(key.slice(2).toLowerCase(), value);
    else node.setAttribute(key, value === true ? '' : value);
  }
  for (const child of children.flat()) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

const num = (n) => Math.round(Number(n) || 0).toLocaleString('ru-RU');

const plural = (n, one, few, many) => {
  const abs = Math.abs(n) % 100;
  const last = abs % 10;
  if (abs > 10 && abs < 20) return many;
  if (last > 1 && last < 5) return few;
  if (last === 1) return one;
  return many;
};

function setStatus(text, busy = false) {
  ui.status.textContent = text;
  ui.status.classList.toggle('status--busy', busy);
}

function showError(message) {
  ui.errorText.textContent = message;
  ui.error.hidden = false;
  ui.error.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

const clearError = () => {
  ui.error.hidden = true;
};

/* ---------- настройки ---------- */

function readOptions() {
  const o = ui.opts;
  return {
    servings: Number(o.servings.value) || 2,
    maxDishes: Number(o.maxDishes.value) || 5,
    meal: o.meal.value,
    diet: o.diet.value,
    kcalTarget: Number(o.kcalTarget.value) || 0,
    notes: o.notes.value.trim(),
    pantry: o.pantry.checked,
    onlyAvailable: o.onlyAvailable.checked,
  };
}

function saveOptions() {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(readOptions()));
  } catch {
    /* приватный режим — не страшно */
  }
}

function restoreOptions() {
  let saved;
  try {
    saved = JSON.parse(localStorage.getItem(STORAGE_KEY) || 'null');
  } catch {
    return;
  }
  if (!saved) return;
  const o = ui.opts;
  if (saved.servings) o.servings.value = saved.servings;
  if (saved.maxDishes) o.maxDishes.value = saved.maxDishes;
  if (saved.meal) o.meal.value = saved.meal;
  if (saved.diet) o.diet.value = saved.diet;
  if (saved.kcalTarget) o.kcalTarget.value = saved.kcalTarget;
  if (typeof saved.notes === 'string') o.notes.value = saved.notes;
  o.pantry.checked = saved.pantry !== false;
  o.onlyAvailable.checked = Boolean(saved.onlyAvailable);
}

/* ---------- фото ---------- */

async function prepareImage(file) {
  if (!file.type.startsWith('image/')) {
    throw new Error(`«${file.name}» — это не изображение.`);
  }
  let bitmap;
  try {
    bitmap = await createImageBitmap(file, { imageOrientation: 'from-image' });
  } catch {
    throw new Error(
      `Не удалось прочитать «${file.name}». Если это HEIC с iPhone, сохраните фото в JPEG.`,
    );
  }
  const scale = Math.min(1, MAX_EDGE / Math.max(bitmap.width, bitmap.height));
  const canvas = document.createElement('canvas');
  canvas.width = Math.round(bitmap.width * scale);
  canvas.height = Math.round(bitmap.height * scale);
  canvas.getContext('2d').drawImage(bitmap, 0, 0, canvas.width, canvas.height);
  bitmap.close?.();

  const dataUrl = canvas.toDataURL('image/jpeg', JPEG_QUALITY);
  const data = dataUrl.slice(dataUrl.indexOf(',') + 1);
  return {
    id: crypto.randomUUID(),
    media_type: 'image/jpeg',
    data,
    preview: dataUrl,
    bytes: Math.round((data.length * 3) / 4),
  };
}

async function addFiles(fileList) {
  const files = [...fileList];
  if (!files.length) return;
  const free = state.maxImages - state.images.length;
  if (free <= 0) {
    showError(`Уже добавлено максимум фото (${state.maxImages}).`);
    return;
  }
  clearError();
  setStatus('Готовим фото…', true);
  const errors = [];
  for (const file of files.slice(0, free)) {
    try {
      state.images.push(await prepareImage(file));
    } catch (err) {
      errors.push(err.message);
    }
  }
  if (files.length > free) errors.push(`Взяли только первые ${free} — это лимит.`);
  setStatus('');
  renderThumbs();
  if (errors.length) showError(errors.join(' '));
}

function renderThumbs() {
  ui.thumbs.replaceChildren(
    ...state.images.map((img) =>
      h(
        'li',
        { class: 'thumb' },
        h('img', { src: img.preview, alt: 'Загруженное фото холодильника' }),
        h('span', { class: 'thumb__size', text: `${Math.round(img.bytes / 1024)} КБ` }),
        h('button', {
          class: 'thumb__remove',
          type: 'button',
          title: 'Убрать фото',
          'aria-label': 'Убрать фото',
          text: '×',
          onclick: () => {
            state.images = state.images.filter((x) => x.id !== img.id);
            renderThumbs();
          },
        }),
      ),
    ),
  );
  ui.thumbs.hidden = state.images.length === 0;
  updateAnalyzeButton();
}

function updateAnalyzeButton() {
  ui.analyze.disabled = state.images.length === 0 || state.busy || !state.ready;
  ui.analyze.title = state.ready ? '' : 'Сначала вставьте ключ API в блоке «Настройка доступа»';
}

/* ---------- запрос ---------- */

async function analyze() {
  if (state.busy || !state.images.length) return;
  state.busy = true;
  ui.analyze.disabled = true;
  clearError();
  saveOptions();
  setStatus('Смотрим на фото, считаем калории и подбираем блюда — это займёт до минуты…', true);

  try {
    const response = await fetch('/api/analyze', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        images: state.images.map(({ media_type, data }) => ({ media_type, data })),
        options: readOptions(),
      }),
    });
    const payload = await response.json().catch(() => ({ error: 'Сервер вернул некорректный ответ.' }));
    if (!response.ok) throw new Error(payload.error || `Ошибка ${response.status}`);
    state.result = payload;
    renderResult(payload);
    setStatus(
      payload.meta?.demo
        ? 'Демо-режим: показан заранее подготовленный пример.'
        : `Готово за ${Math.round((payload.meta?.elapsed_ms || 0) / 1000)} с.`,
    );
    ui.reset.hidden = false;
    ui.results.scrollIntoView({ behavior: 'smooth', block: 'start' });
  } catch (err) {
    setStatus('');
    showError(err.message || 'Не удалось связаться с сервером.');
  } finally {
    state.busy = false;
    updateAnalyzeButton();
  }
}

/* ---------- вывод результата ---------- */

function renderResult(result) {
  const products = result.products || [];
  const dishes = result.dishes || [];

  const readyCount = dishes.filter((d) => d.ready_now).length;
  const avgKcal = dishes.length
    ? Math.round(dishes.reduce((s, d) => s + (d.per_serving?.kcal || 0), 0) / dishes.length)
    : 0;

  ui.summary.replaceChildren(
    stat(num(products.length), plural(products.length, 'продукт', 'продукта', 'продуктов') + ' найдено'),
    stat(num(result.total_kcal), 'ккал в холодильнике'),
    stat(num(dishes.length), `${plural(dishes.length, 'блюдо', 'блюда', 'блюд')} подобрано`),
    stat(readyCount ? `${readyCount} из ${dishes.length}` : '—', 'можно готовить сейчас'),
    avgKcal ? stat(num(avgKcal), 'ккал в порции в среднем') : null,
  );

  ui.productsCount.textContent = products.length
    ? `${num(result.total_kcal)} ккал всего`
    : 'ничего не распознано';

  ui.productsBody.replaceChildren(
    ...products.map((p) =>
      h(
        'tr',
        {},
        h(
          'td',
          { class: 'table__name' },
          p.confidence === 'низкая'
            ? h('span', { class: 'dot dot--low', title: 'Распознано неуверенно' })
            : null,
          p.name,
          h('span', { class: 'table__cat', text: p.category || '' }),
        ),
        h('td', { text: p.amount || '—' }),
        h('td', { class: 'num', text: `${num(p.grams)} г` }),
        h('td', { class: 'num', text: num(p.kcal_per_100g) }),
        h('td', { class: 'num', text: num(p.kcal) }),
      ),
    ),
  );

  renderDishes();

  ui.notes.textContent = result.notes || '';
  ui.notes.hidden = !result.notes;
  ui.results.hidden = false;
}

function stat(value, label) {
  return h('div', { class: 'stat' }, h('div', { class: 'stat__value', text: value }), h('div', { class: 'stat__label', text: label }));
}

function renderDishes() {
  let dishes = [...(state.result?.dishes || [])];
  if (ui.filterReady.checked) dishes = dishes.filter((d) => d.ready_now);

  const by = ui.sortDishes.value;
  if (by === 'kcal-asc') dishes.sort((a, b) => a.per_serving.kcal - b.per_serving.kcal);
  if (by === 'kcal-desc') dishes.sort((a, b) => b.per_serving.kcal - a.per_serving.kcal);
  if (by === 'time') dishes.sort((a, b) => a.time_minutes - b.time_minutes);
  if (by === 'protein') dishes.sort((a, b) => b.per_serving.protein_g - a.per_serving.protein_g);

  if (!dishes.length) {
    ui.dishes.replaceChildren(
      h('p', {
        class: 'empty',
        text: ui.filterReady.checked
          ? 'Ни одно блюдо не готовится без докупок — снимите фильтр, чтобы увидеть остальные.'
          : 'Блюда не подобраны. Попробуйте другое фото или ослабьте ограничения.',
      }),
    );
    return;
  }
  ui.dishes.replaceChildren(...dishes.map(dishCard));
}

function dishCard(dish) {
  const ps = dish.per_serving || {};
  const badges = [
    dish.ready_now
      ? h('span', { class: 'badge badge--ok', text: '✓ всё есть' })
      : h('span', {
          class: 'badge badge--warn',
          text: `нужно докупить: ${dish.missing.join(', ')}`,
        }),
    h('span', { class: 'badge', text: `${dish.time_minutes} мин` }),
    h('span', { class: 'badge', text: dish.difficulty }),
    h('span', {
      class: 'badge',
      text: `${dish.servings} ${plural(dish.servings, 'порция', 'порции', 'порций')}`,
    }),
  ];

  return h(
    'article',
    { class: 'dish' },
    h(
      'div',
      { class: 'dish__head' },
      h('h3', { class: 'dish__name', text: dish.name }),
      h('div', { class: 'dish__kcal' }, `${num(ps.kcal)} ккал `, h('span', { text: '/ порция' })),
    ),
    dish.description ? h('p', { class: 'dish__desc', text: dish.description }) : null,
    h('div', { class: 'dish__badges' }, badges),
    h(
      'div',
      { class: 'macros' },
      macro('Белки', `${num(ps.protein_g)} г`),
      macro('Жиры', `${num(ps.fat_g)} г`),
      macro('Углеводы', `${num(ps.carbs_g)} г`),
      macro('Всего на блюдо', `${num(dish.total?.kcal)} ккал`),
    ),
    h(
      'details',
      {},
      h('summary', { text: 'Состав и приготовление' }),
      h('p', { class: 'subhead', text: 'Ингредиенты' }),
      h(
        'ul',
        { class: 'ing' },
        (dish.ingredients || []).map((ing) =>
          h(
            'li',
            {},
            h(
              'span',
              { class: ing.available ? '' : 'ing__miss' },
              `${ing.product} — ${ing.amount}`,
              ing.available ? '' : ' (нет в наличии)',
            ),
            h('span', { class: 'ing__kcal', text: `${num(ing.kcal)} ккал` }),
          ),
        ),
      ),
      h('p', { class: 'subhead', text: 'Приготовление' }),
      h('ol', { class: 'steps' }, (dish.steps || []).map((step) => h('li', { text: step }))),
    ),
  );
}

function macro(label, value) {
  return h('div', {}, h('b', { text: value }), label);
}

/* ---------- инициализация ---------- */

function fillSelect(select, dict) {
  select.replaceChildren(
    ...Object.entries(dict).map(([value, label]) => h('option', { value, text: label })),
  );
}

const KEY_STATE = {
  demo: ['демо-режим', 'badge'],
  env: ['ключ задан в системе', 'badge badge--ok'],
  file: ['ключ сохранён', 'badge badge--ok'],
  none: ['нужен ключ API', 'badge badge--warn'],
};

function applyConfig(config) {
  state.maxImages = config.maxImages || 4;
  state.ready = Boolean(config.ready);
  ui.maxImages.textContent = String(state.maxImages);

  fillSelect(ui.opts.meal, config.meals);
  fillSelect(ui.opts.diet, config.diets);
  fillSelect(ui.model, config.models);
  fillSelect(ui.effort, config.efforts);
  if (config.model) ui.model.value = config.model;
  if (config.effort) ui.effort.value = config.effort;

  const [label, cls] = KEY_STATE[config.keySource] || KEY_STATE.none;
  ui.setupState.textContent = label;
  ui.setupState.className = cls;
  ui.modelBadge.textContent = config.demo ? 'демо-режим' : config.model;
  ui.modelBadge.hidden = false;

  // Блок настроек раскрыт, пока ключа нет; когда всё готово — свёрнут.
  if (!state.ready) ui.setup.open = true;
  if (config.keySource === 'env') {
    ui.key.placeholder = 'ключ берётся из переменной окружения';
    ui.key.disabled = true;
  }
  updateAnalyzeButton();
}

async function saveSettings() {
  ui.saveSettings.disabled = true;
  ui.setupStatus.textContent = 'Сохраняем и проверяем ключ…';
  ui.setupStatus.classList.add('status--busy');
  try {
    const patch = { model: ui.model.value, effort: ui.effort.value };
    if (ui.key.value.trim()) patch.apiKey = ui.key.value.trim();

    const response = await fetch('/api/settings', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(patch),
    });
    const config = await response.json();
    if (!response.ok) throw new Error(config.error || `Ошибка ${response.status}`);

    applyConfig(config);
    ui.key.value = '';
    if (config.check?.ok) {
      ui.setupStatus.textContent = '✓ Ключ работает, можно загружать фото.';
      state.ready = true;
      updateAnalyzeButton();
      setTimeout(() => (ui.setup.open = false), 900);
    } else {
      ui.setupStatus.textContent = `Сохранено, но проверка не прошла: ${config.check?.error || 'неизвестная ошибка'}`;
      ui.setupState.textContent = 'ключ не прошёл проверку';
      ui.setupState.className = 'badge badge--warn';
    }
  } catch (err) {
    ui.setupStatus.textContent = err.message || 'Не удалось сохранить настройки.';
  } finally {
    ui.setupStatus.classList.remove('status--busy');
    ui.saveSettings.disabled = false;
  }
}

async function init() {
  try {
    applyConfig(await fetch('/api/config').then((r) => r.json()));
  } catch {
    showError('Сервер не отвечает. Запустите приложение заново («Запустить» в папке fridge).');
  }
  restoreOptions();

  ui.fileInput.addEventListener('change', (e) => {
    addFiles(e.target.files);
    e.target.value = '';
  });

  for (const [event, handler] of [
    ['dragover', (e) => (e.preventDefault(), ui.dropzone.classList.add('is-over'))],
    ['dragleave', () => ui.dropzone.classList.remove('is-over')],
    [
      'drop',
      (e) => {
        e.preventDefault();
        ui.dropzone.classList.remove('is-over');
        addFiles(e.dataTransfer.files);
      },
    ],
  ]) {
    ui.dropzone.addEventListener(event, handler);
  }

  document.addEventListener('paste', (e) => {
    const files = [...(e.clipboardData?.files || [])];
    if (files.length) addFiles(files);
  });

  ui.analyze.addEventListener('click', analyze);
  ui.reset.addEventListener('click', () => {
    state.images = [];
    state.result = null;
    ui.results.hidden = true;
    ui.reset.hidden = true;
    clearError();
    setStatus('');
    renderThumbs();
    window.scrollTo({ top: 0, behavior: 'smooth' });
  });

  ui.saveSettings.addEventListener('click', saveSettings);
  ui.key.addEventListener('keydown', (e) => e.key === 'Enter' && saveSettings());
  ui.filterReady.addEventListener('change', renderDishes);
  ui.sortDishes.addEventListener('change', renderDishes);
  for (const field of Object.values(ui.opts)) field.addEventListener('change', saveOptions);
}

init();
