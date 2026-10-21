import { useState } from "react";

/** Фон-студия на весь экран. Файл bg.studio.webp подхватывается сам, если лежит в assets. */
export function Studio() {
  const [ok, setOk] = useState(true);
  return <div className="studio">{ok && <img src="/assets/bg.studio.webp" alt="" onError={() => setOk(false)} />}</div>;
}
