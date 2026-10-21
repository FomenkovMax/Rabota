import { Howl } from "howler";

// Звуки по ID из assets/ASSET_SPEC.md (sfx.spin, sfx.tick, sfx.timer10, sfx.ok, sfx.fail). Нет файла — тишина, без ошибок.
export type Sfx = "spin" | "tick" | "timer10" | "ok" | "fail";

const KEY = "chgk.muted";
let muted = false;
try { muted = localStorage.getItem(KEY) === "1"; } catch { /* приватный режим */ }

const cache = new Map<Sfx, Howl | null>();
function load(id: Sfx): Howl | null {
  if (!cache.has(id)) {
    const h = new Howl({ src: [`/assets/sfx.${id}.mp3`], volume: 0.7, html5: false, onloaderror: () => cache.set(id, null) });
    cache.set(id, h);
  }
  return cache.get(id) ?? null;
}

export const sound = {
  play(id: Sfx) { if (!muted) load(id)?.play(); },
  isMuted: () => muted,
  toggle() {
    muted = !muted;
    try { localStorage.setItem(KEY, muted ? "1" : "0"); } catch { /* ignore */ }
    return muted;
  },
};
