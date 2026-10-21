import { useState } from "react";
import { sound } from "../sound";
import { useApp } from "../store";
import { Asset } from "../components/Asset";
import { Button } from "../components/Button";
import { Card } from "../components/Card";
import s from "./Screen.module.css";

export function Home() {
  const { me, go } = useApp();
  const [muted, setMuted] = useState(sound.isMuted());
  if (!me) return null;
  const st = me.stats;
  return (
    <div className={s.wrap}>
      <div className={s.center}>
        <Asset id="home.logo" fallback="🦉" size={110} />
        <h1>{me.brand.game_name}</h1>
        <p className={s.dim}>Привет, {me.user.name}!</p>
      </div>
      <Card>
        <div className={s.stats}>
          <div><b>{st.played}</b><span>вопросов</span></div>
          <div><b>{st.correct}</b><span>взято</span></div>
          <div><b>{st.points}</b><span>очков</span></div>
        </div>
      </Card>
      <Button onClick={() => go("solo")}>Играть соло</Button>
      <Button variant="ghost" onClick={() => go("team")}>Командная игра</Button>
      <Button variant="ghost" onClick={() => setMuted(sound.toggle())}>{muted ? "🔇 Звук выключен" : "🔊 Звук включён"}</Button>
    </div>
  );
}
