import { AnimatePresence, motion } from "framer-motion";
import { useEffect, useRef, useState } from "react";
import { openRoom, type RoomState } from "../api";
import { Button } from "../components/Button";
import { Card } from "../components/Card";
import { TimerRing } from "../components/TimerRing";
import { Wheel } from "../components/Wheel";
import { useApp } from "../store";
import { tg } from "../tg";
import s from "./Screen.module.css";

const ACCENT = { correct: "ok", close: "half", wrong: "bad" } as const;

export function Team() {
  const { me, go } = useApp();
  const [room, setRoom] = useState<RoomState | null>(null);
  const [offset, setOffset] = useState(0);
  const [err, setErr] = useState("");
  const [text, setText] = useState("");
  const conn = useRef<ReturnType<typeof openRoom> | null>(null);
  const lastIdx = useRef(-2);

  useEffect(() => {
    conn.current = openRoom(
      (st) => { setRoom(st); setOffset(st.server_now_ms - Date.now()); setErr(""); },
      (m) => { setErr(m); tg.haptic("error"); },
    );
    return () => conn.current?.close();
  }, []);

  const send = (msg: Record<string, unknown>) => conn.current?.send(msg);
  const g = room?.game ?? null;
  const isCaptain = !!g && g.captain_id === me?.user.id;
  const nameOf = (id: number) => room?.players.find((p) => p.id === id)?.name ?? "—";

  useEffect(() => { if (g && g.idx !== lastIdx.current) { lastIdx.current = g.idx; setText(""); } }, [g]);

  const header = (
    <Card>
      {g?.mode === "wheel" ? (
        <div className={s.stats}><div><b>{g.experts}</b><span>знатоки</span></div><div><b>{g.viewers}</b><span>телезрители</span></div></div>
      ) : g ? (
        <div className={s.stats}><div><b>{g.score}</b><span>очков</span></div><div><b>{g.tour ? `${g.tour[0]}·${g.tour[1]}` : "—"}</b><span>тур·вопрос</span></div><div><b>{g.idx + 1}/{g.total}</b><span>всего</span></div></div>
      ) : null}
      {g && <p className={s.dim} style={{ marginTop: 8 }}>Капитан: {nameOf(g.captain_id)}{isCaptain ? " (ты)" : ""}</p>}
    </Card>
  );

  return (
    <div className={s.wrap}>
      <p className={s.dim}>В комнате: {room?.players.map((p) => p.name).join(", ") || "…"}</p>
      {err && <Card accent="bad">{err}</Card>}

      {!g || g.status === "finished" ? (
        <>
          {g?.status === "finished" && (
            <Card accent="ok">
              <h2>Игра окончена 🏁</h2>
              <p className={s.dim}>{g.mode === "wheel" ? `Знатоки ${g.experts} : ${g.viewers} телезрители` : `Очков: ${g.score} из ${g.total}`}</p>
              {g.log?.map((r, i) => <p key={i} className={s.step}>{i + 1}. {r.level === "correct" ? "✅" : r.level === "close" ? "🟡" : "❌"} {r.answer ?? "— нет ответа"}</p>)}
            </Card>
          )}
          <Card><h2>Новая игра</h2><p className={s.dim}>Кто нажмёт «Начать» — становится капитаном.</p></Card>
          <Button onClick={() => send({ type: "start", mode: "sport", tours: 3, per_tour: 12 })}>Спортивное ЧГК · 3 тура по 12</Button>
          <Button variant="ghost" onClick={() => send({ type: "start", mode: "sport", tours: 1, per_tour: 6 })}>Короткая · 6 вопросов</Button>
          <Button variant="ghost" onClick={() => send({ type: "start", mode: "wheel" })}>🎡 Классический волчок</Button>
          <Button variant="ghost" onClick={() => go("home")}>В меню</Button>
        </>
      ) : (
        <>
          {header}
          {g.mode === "wheel" && (
            <div className={s.center}>
              <Wheel n={g.total} played={g.played} spin={g.spin} spinKey={g.idx} />
            </div>
          )}
          <AnimatePresence mode="wait">
            <motion.div key={g.phase + g.idx} className={s.col} initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}>
              {(g.phase === "think" || g.phase === "answer") && (
                <div className={s.center}>
                  <TimerRing deadlineMs={g.deadline_ms} offsetMs={offset} totalSec={g.phase === "think" ? g.think : 20} />
                  <p className={s.dim}>{g.phase === "think" ? "Обсуждаем" : "Время сдавать ответ!"}</p>
                </div>
              )}
              {g.question && <Card><p className={s.question}>{g.question.text}</p></Card>}

              {(g.phase === "think" || g.phase === "answer") && (isCaptain ? (
                <>
                  <input className={s.input} value={text} placeholder="Ответ команды" onChange={(e) => setText(e.target.value)} />
                  <Button disabled={!text.trim()} onClick={() => send({ type: "answer", text })}>Сдать ответ</Button>
                </>
              ) : <p className={s.dim}>Ответ сдаёт капитан.</p>)}

              {g.phase === "judging" && <p className={s.dim}>Ответ «{g.answer}» — судья думает…</p>}

              {g.phase === "review" && g.verdict && (
                <>
                  <Card accent={ACCENT[g.verdict.level]}>
                    <h2>{g.verdict.level === "correct" ? "Верно! 🎉" : g.verdict.level === "close" ? "Почти 🤏" : "Мимо"}</h2>
                    <p className={s.dim}>Ответ команды: {g.answer ?? "— не успели"}</p>
                    <p className={s.dim}>{g.verdict.comment}</p>
                    {g.verdict.disputed && <p className={s.dim}>⚠️ Судья не ответил — решает капитан.</p>}
                  </Card>
                  {g.reveal && <Card><p className={s.dim}>Ответ</p><h2>{g.reveal.answer}</h2><p className={s.explain}>{g.reveal.explanation}</p></Card>}
                  {isCaptain && (
                    <>
                      <Button variant="ghost" onClick={() => send({ type: "override", correct: g.verdict!.level !== "correct" })}>
                        {g.verdict.level === "correct" ? "Не засчитывать" : "Засчитать"}
                      </Button>
                      <Button onClick={() => send({ type: "next" })}>{g.idx + 1 >= g.total ? "Завершить" : "Дальше"}</Button>
                    </>
                  )}
                </>
              )}
            </motion.div>
          </AnimatePresence>
          {isCaptain && <Button variant="ghost" onClick={() => send({ type: "stop" })}>Закончить игру</Button>}
        </>
      )}
    </div>
  );
}
