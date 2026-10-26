import { useEffect, useState } from "react";
import { api, type ActorStats, type TeamStats } from "../api";
import { BarChart } from "../components/BarChart";
import { Button } from "../components/Button";
import { MenuButton } from "../components/MenuButton";
import { Card } from "../components/Card";
import { useApp } from "../store";
import s from "./Screen.module.css";

type Scope = "me" | "team";

export function Stats() {
  const { go } = useApp();
  const [scope, setScope] = useState<Scope>("me");
  const [data, setData] = useState<ActorStats | TeamStats | null>(null);
  const [card, setCard] = useState("");
  const [msg, setMsg] = useState("");

  useEffect(() => {
    setData(null); setCard("");
    (scope === "me" ? api.statsMe() : api.statsTeam()).then(setData).catch((e) => setMsg(e.message));
  }, [scope]);

  const team = data && "games" in data ? (data as TeamStats) : null;   // данные приходят с задержкой: смотрим на сами данные, а не на выбранную вкладку
  return (
    <div className={s.wrap}>
      <div style={{ display: "flex", gap: 8 }}>
        <Button variant={scope === "me" ? "primary" : "ghost"} onClick={() => setScope("me")}>Я</Button>
        <Button variant={scope === "team" ? "primary" : "ghost"} onClick={() => setScope("team")}>Команда</Button>
      </div>
      {msg && <Card accent="bad">{msg}</Card>}
      {!data && !msg && <p className={s.dim}>Считаю…</p>}
      {data && (
        <>
          <Card>
            <div className={s.stats}>
              <div><b>{data.played}</b><span>вопросов</span></div>
              <div><b>{data.played ? Math.round(data.accuracy * 100) : 0}%</b><span>точность</span></div>
              <div><b>{data.best_streak}</b><span>лучшая серия</span></div>
            </div>
            <p className={s.dim} style={{ marginTop: 10 }}>
              Взято {data.correct}, почти {data.close}, очков {data.points}
              {data.avg_time_ms ? ` · ответ в среднем за ${Math.round(data.avg_time_ms / 1000)} с` : ""}
            </p>
          </Card>
          <Card><p className={s.dim}>Последние 14 дней</p><BarChart data={data.daily} /></Card>
          {data.packs.length > 0 && (
            <Card>
              <p className={s.dim}>Пакеты</p>
              {data.packs.map((p) => (
                <p key={p.name} className={s.step}>{p.name}: <b>{p.correct}/{p.played}</b> ({Math.round((100 * p.correct) / p.played)}%)</p>
              ))}
            </Card>
          )}
          {team && team.games.length > 0 && (
            <Card>
              <p className={s.dim}>Игры команды</p>
              {team.games.map((g, i) => (
                <p key={i} className={s.step}>{g.date} · {g.mode === "wheel" ? `волчок ${g.experts}:${g.viewers}` : `${g.score}/${g.total}`}</p>
              ))}
            </Card>
          )}
          {team && team.players.length > 0 && (
            <Card>
              <p className={s.dim}>Вклад игроков</p>
              {team.players.map((p) => (
                <p key={p.id} className={s.step}>{p.name}: соло {p.solo_correct}/{p.solo_played}, капитаном {p.captain_correct}/{p.as_captain}</p>
              ))}
            </Card>
          )}
          {!team && data.recent.length > 0 && (
            <Card>
              <p className={s.dim}>Недавние</p>
              {data.recent.map((r, i) => <p key={i} className={s.step}>{r.score >= 1 ? "✅" : r.score > 0 ? "🟡" : "❌"} {r.text}…</p>)}
            </Card>
          )}
          {card ? <img src={card} alt="Карточка-итог" style={{ width: "100%", borderRadius: 14 }} />
            : <Button variant="ghost" onClick={() => api.cardBlob(scope).then(setCard).catch((e) => setMsg(e.message))}>🖼 Карточка-итог</Button>}
          <Button variant="ghost" onClick={() => api.sendCard(scope).then(() => setMsg("Карточка отправлена тебе в личку бота — перешли её в чат")).catch((e) => setMsg(e.message))}>
            📤 Прислать карточку в чат с ботом
          </Button>
        </>
      )}
      <MenuButton />
    </div>
  );
}
