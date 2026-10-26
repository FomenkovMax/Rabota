import { AnimatePresence, motion } from "framer-motion";
import { useEffect } from "react";
import { Asset } from "./components/Asset";
import { Card } from "./components/Card";
import { Studio } from "./components/Studio";
import { Admin } from "./screens/Admin";
import { Home } from "./screens/Home";
import { Season } from "./screens/Season";
import { Solo } from "./screens/Solo";
import { Stats } from "./screens/Stats";
import { Team } from "./screens/Team";
import { useApp } from "./store";
import { tg } from "./tg";

const SCREENS = { home: Home, solo: Solo, team: Team, stats: Stats, season: Season, admin: Admin };

export function App() {
  const { me, error, screen, dir, boot, go } = useApp();
  useEffect(() => { tg.init(); void boot(); }, [boot]);
  // «Назад» в шапке Telegram: на любом экране, кроме главного
  useEffect(() => tg.backButton(screen === "home" ? null : () => go("home")), [screen, go]);

  let body;
  if (error) body = <div style={{ padding: 16 }}><Card accent="bad">{error}</Card></div>;
  else if (!me) body = (
    <div style={{ padding: 24, minHeight: "60vh", display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 12, color: "var(--text-dim)" }}>
      <motion.div animate={{ y: [0, -8, 0] }} transition={{ duration: 1.6, repeat: Infinity, ease: "easeInOut" }}>
        <Asset id="loader" fallback="🦉" size={96} />
      </motion.div>
      <p>Загрузка…</p>
    </div>
  );
  else {
    const Screen = SCREENS[screen];
    body = (
      <AnimatePresence mode="wait" initial={false} custom={dir}>
        <motion.div key={screen} custom={dir}
          initial={{ opacity: 0, x: 40 * dir }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: -40 * dir }}
          transition={{ duration: 0.22, ease: "easeOut" }}>
          <Screen />
        </motion.div>
      </AnimatePresence>
    );
  }
  return <><Studio />{body}</>;
}
