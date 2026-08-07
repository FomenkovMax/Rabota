import { MAX_IMAGES, MEALS, DIETS, hasCredentials } from '../../src/analyze.js';
import { getModel, getEffort, keySource, MODEL_CHOICES, EFFORT_CHOICES } from '../../src/settings.js';

export default async () => {
  const demo = process.env.FRIDGE_DEMO === '1';
  return new Response(
    JSON.stringify({
      model: demo ? 'demo' : getModel(),
      effort: getEffort(),
      demo,
      ready: demo || hasCredentials(),
      keySource: demo ? 'demo' : keySource(),
      // В serverless-режиме файловых настроек нет: ключ задаётся переменной окружения.
      settingsFile: null,
      maxImages: MAX_IMAGES,
      meals: MEALS,
      diets: DIETS,
      models: MODEL_CHOICES,
      efforts: EFFORT_CHOICES,
    }),
    { headers: { 'content-type': 'application/json; charset=utf-8', 'cache-control': 'no-store' } },
  );
};

export const config = { path: '/api/config' };
