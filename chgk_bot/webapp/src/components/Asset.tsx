import { useState } from "react";

/** Картинка по ID из assets/ASSET_SPEC.md. Нет файла — показываем запасной эмодзи, код менять не нужно. */
export function Asset({ id, fallback, size = 96 }: { id: string; fallback: string; size?: number }) {
  const [broken, setBroken] = useState(false);
  if (broken) return <span style={{ fontSize: size * 0.7, lineHeight: 1 }}>{fallback}</span>;
  return <img src={`/assets/${id}.webp`} width={size} height={size} alt="" onError={() => setBroken(true)} />;
}
