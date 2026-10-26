import { motion } from "framer-motion";
import { useState } from "react";
import { CountUp } from "../components/CountUp";
import { OwlHero } from "../components/OwlHero";
import { Tile } from "../components/Tile";
import { sound } from "../sound";
import { useApp } from "../store";
import s from "./Screen.module.css";

export function Home() {
  const { me, go } = useApp();
  const [muted, setMuted] = useState(sound.isMuted());
  if (!me) return null;
  const st = me.stats;
  const acc = st.played ? Math.round((100 * st.correct) / st.played) : 0;
  return (
    <div className={s.wrap}>
      <div className={s.center} style={{ gap: 2 }}>
        <OwlHero />
        <motion.h1 className="gold-text" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} style={{ textAlign: "center" }}>
          Что? Где? Когда?
        </motion.h1>
        <p className={s.dim}>Тренировка знатоков · привет, {me.user.name}!</p>
      </div>

      <motion.div className={s.strip} initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: 0.15 }}>
        <div><b><CountUp value={st.played} /></b><span>вопросов</span></div>
        <i />
        <div><b><CountUp value={st.correct} /></b><span>взято</span></div>
        <i />
        <div><b><CountUp value={acc} suffix="%" /></b><span>точность</span></div>
      </motion.div>

      <div className={s.grid}>
        <Tile id="tile.solo" fallback="🧠" title="Соло" sub="минута на вопрос" accent delay={0.05} onClick={() => go("solo")} />
        <Tile id="tile.team" fallback="🎡" title="Команда" sub="волчок и туры" delay={0.1} onClick={() => go("team")} />
        <Tile id="tile.season" fallback="🏆" title="Сезон" sub="лиги и совы" delay={0.15} onClick={() => go("season")} />
        <Tile id="tile.stats" fallback="📊" title="Статистика" sub="прогресс и итоги" delay={0.2} onClick={() => go("stats")} />
      </div>

      <div className={s.chips}>
        <button className={s.chip} onClick={() => setMuted(sound.toggle())}>{muted ? "🔇 Звук выкл." : "🔊 Звук вкл."}</button>
        {me.is_admin && <button className={s.chip} onClick={() => go("admin")}>🛠 Вопросы</button>}
      </div>
    </div>
  );
}
