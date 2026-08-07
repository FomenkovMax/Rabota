import { MAX_IMAGES, MEALS, DIETS, MODEL, hasCredentials } from '../../src/analyze.js';

export default async () => {
  const demo = process.env.FRIDGE_DEMO === '1';
  return new Response(
    JSON.stringify({
      model: demo ? 'demo' : MODEL,
      demo,
      ready: demo || hasCredentials(),
      maxImages: MAX_IMAGES,
      meals: MEALS,
      diets: DIETS,
    }),
    { headers: { 'content-type': 'application/json; charset=utf-8', 'cache-control': 'no-store' } },
  );
};

export const config = { path: '/api/config' };
