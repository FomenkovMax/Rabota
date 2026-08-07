// JSON-схема ответа модели. Передаётся в output_config.format (structured outputs),
// поэтому подчиняется ограничениям: у каждого объекта additionalProperties: false и
// полный список required; числовые/строковые ограничения (minimum, minLength и т.п.)
// не поддерживаются и намеренно не используются.

const nutrition = (what) => ({
  type: 'object',
  additionalProperties: false,
  required: ['kcal', 'protein_g', 'fat_g', 'carbs_g'],
  description: what,
  properties: {
    kcal: { type: 'number', description: 'килокалории' },
    protein_g: { type: 'number', description: 'белки, г' },
    fat_g: { type: 'number', description: 'жиры, г' },
    carbs_g: { type: 'number', description: 'углеводы, г' },
  },
});

export const PRODUCT_CATEGORIES = [
  'овощи',
  'фрукты и ягоды',
  'молочное',
  'мясо',
  'рыба и морепродукты',
  'яйца',
  'крупы и мука',
  'хлеб',
  'соусы и масла',
  'напитки',
  'заготовки и консервы',
  'сладкое',
  'другое',
];

export const RESULT_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  required: ['products', 'total_kcal', 'dishes', 'notes'],
  properties: {
    products: {
      type: 'array',
      description: 'Продукты, которые реально видно на фото. Ничего не выдумывать.',
      items: {
        type: 'object',
        additionalProperties: false,
        required: ['name', 'amount', 'grams', 'kcal_per_100g', 'kcal', 'category', 'confidence'],
        properties: {
          name: { type: 'string', description: 'название продукта' },
          amount: {
            type: 'string',
            description: 'количество как на фото: «6 шт», «пачка ~400 г», «половина кочана»',
          },
          grams: { type: 'number', description: 'оценка съедобной массы в граммах' },
          kcal_per_100g: { type: 'number', description: 'калорийность на 100 г' },
          kcal: { type: 'number', description: 'калорийность всего количества' },
          category: { type: 'string', enum: PRODUCT_CATEGORIES },
          confidence: {
            type: 'string',
            enum: ['высокая', 'средняя', 'низкая'],
            description: 'насколько уверенно продукт опознан и оценён по массе',
          },
        },
      },
    },
    total_kcal: {
      type: 'number',
      description: 'сумма kcal по всем распознанным продуктам',
    },
    dishes: {
      type: 'array',
      description: 'Блюда, которые можно приготовить, от самых полно использующих запасы',
      items: {
        type: 'object',
        additionalProperties: false,
        required: [
          'name',
          'description',
          'servings',
          'time_minutes',
          'difficulty',
          'ingredients',
          'missing',
          'per_serving',
          'total',
          'steps',
          'ready_now',
        ],
        properties: {
          name: { type: 'string' },
          description: { type: 'string', description: 'одно предложение: что это и почему подходит' },
          servings: { type: 'integer', description: 'на сколько порций рассчитан рецепт' },
          time_minutes: { type: 'integer', description: 'время приготовления в минутах' },
          difficulty: { type: 'string', enum: ['просто', 'средне', 'сложно'] },
          ingredients: {
            type: 'array',
            items: {
              type: 'object',
              additionalProperties: false,
              required: ['product', 'amount', 'grams', 'kcal', 'available'],
              properties: {
                product: { type: 'string' },
                amount: { type: 'string', description: 'бытовая мера: «2 шт», «150 г», «1 ст. л.»' },
                grams: { type: 'number' },
                kcal: { type: 'number', description: 'калорийность этого количества' },
                available: { type: 'boolean', description: 'есть ли продукт на фото' },
              },
            },
          },
          missing: {
            type: 'array',
            description: 'чего не хватает — то, чего нет на фото и что не входит в базовый набор',
            items: { type: 'string' },
          },
          per_serving: nutrition('КБЖУ одной порции'),
          total: nutrition('КБЖУ всего блюда'),
          steps: {
            type: 'array',
            description: '3–7 коротких шагов приготовления',
            items: { type: 'string' },
          },
          ready_now: {
            type: 'boolean',
            description: 'true, если блюдо готовится только из того, что есть (missing пуст)',
          },
        },
      },
    },
    notes: {
      type: 'string',
      description:
        'Короткий комментарий: что мешало распознаванию, что скоро испортится, чего не хватает для разнообразия. Пустая строка, если сказать нечего.',
    },
  },
};
