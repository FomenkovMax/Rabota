// Служебная страница: по ней видно, какая ревизия кода сейчас на проде.
// Нужна, когда деплой оборвался на полпути и неясно, доехал он или нет.

import { provider, activeModel } from '../lib/analyze.js';

export const REVISION = 4;

export default function handler(req, res) {
  res.status(200).json({
    revision: REVISION,
    provider: provider(),
    models: activeModel().split(', '),
  });
}
