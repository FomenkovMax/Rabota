import { AnimatePresence, motion } from "framer-motion";
import { useEffect, useRef, useState } from "react";
import { openRoom, type RoomState } from "../api";
import { Button } from "../components/Button";
import { MenuButton } from "../components/MenuButton";
import { Card } from "../components/Card";
import { TimerRing } from "../components/TimerRing";
import { Wheel } from "../components/Wheel";
import { useApp } from "../store";
import { sound } from "../sound";
import { tg } from "../tg";
import { Asset } from "../components/Asset";
import { Avatar } from "../components/Avatar";
import { TableLobby } from "../components/TableLobby";
import { Confetti } from "../components/Confetti";
import { QuestionCard } from "../components/QuestionCard";
import { Scoreboard } from "../components/Scoreboard";
import { VerdictBadge } from "../components/VerdictBadge";
import { Envelope } from "../components/Envelope";
import s from "./Screen.module.css";

const ACCENT = { correct: "ok", close: "half", wrong: "bad" } as const;

export function Team() {
  const { me, go } = useApp();
  const [room, setRoom] = useState<RoomState | null>(null);
  const [offset, setOffset] = useState(0);
  const [err, setErr] = useState("");
  const [online, setOnline] = useState(false);
  const [slow, setSlow] = useState(false);   // долго нет связи — показываем подсказку вместо вечного «Подключаюсь…»
  const [text, setText] = useState("");
  const conn = useRef<ReturnType<typeof openRoom> | null>(null);
  const lastIdx = useRef(-2);
  const [opened, setOpened] = useState(false);     // волчок остановился и конверт открыт
  const lastVerdict = useRef("");

  useEffect(() => {
    conn.current = openRoom(
      (st) => { setRoom(st); setOffset(st.server_now_ms - Date.now()); setErr(""); },
      (m) => { setErr(m); tg.haptic("error"); },
      (up) => setOnline(up),
    );
    return () => conn.current?.close();
  }, []);

  useEffect(() => {
    if (online) { setSlow(false); return; }
    const t = setTimeout(() => setSlow(true), 5000);
    return () => clearTimeout(t);
  }, [online]);
  const send = (msg: Record<string, unknown>) => conn.current?.send(msg);
  const g = room?.game ?? null;
  const isCaptain = !!g && g.captain_id === me?.user.id;
  const nameOf = (id: number) => room?.players.find((p) => p.id === id)?.name ?? "—";

  useEffect(() => { if (g && g.idx !== lastIdx.current) { lastIdx.current = g.idx; setText(""); setOpened(false); } }, [g]);
  useEffect(() => {
    const key = g?.phase === "review" && g.verdict ? `${g.idx}:${g.verdict.level}` : "";
    if (key && key !== lastVerdict.current) { sound.play(g!.verdict!.level === "wrong" ? "fail" : "ok"); tg.haptic(g!.verdict!.level === "wrong" ? "error" : "success"); }
    lastVerdict.current = key;
  }, [g]);
  const wheelWait = g?.mode === "wheel" && !opened && (g.phase === "think");

  const header = g && (
    g.mode === "wheel" ? (
      <Scoreboard sep=":" caption={`Капитан: ${nameOf(g.captain_id)}${isCaptain ? " (ты)" : ""} · игра до 6`}
        cells={[{ label: "знатоки", value: g.experts, hot: g.experts > g.viewers }, { label: "телезрители", value: g.viewers, hot: g.viewers > g.experts }]} />
    ) : (
      <Scoreboard caption={`Капитан: ${nameOf(g.captain_id)}${isCaptain ? " (ты)" : ""}`}
        cells={[{ label: "очков", value: g.score, hot: true }, { label: "тур", value: g.tour ? g.tour[0] : "—" }, { label: "вопрос", value: `${g.idx + 1}/${g.total}` }]} />
    )
  );

  return (
    <div className={s.wrap}>
      {(!g || g.status === "finished") ? (
        <div className={s.center} style={{ gap: 4 }}>
          <h2 className="gold-text">Стол знатоков</h2>
          <p className={s.dim}>{online && room ? `За столом: ${room.players.length}` : slow ? "Нет связи с комнатой — пробую снова…" : "Подключаюсь…"}</p>
          <TableLobby players={room?.players ?? []} meId={me?.user.id} />
        </div>
      ) : (
        <div className={s.avatars}>
          {room?.players.map((p) => <Avatar key={p.id} id={p.id} name={p.name} photo={p.photo} size={36} crown={p.id === g.captain_id} />)}
        </div>
      )}
      {err && <Card accent="bad">{err}</Card>}

      {!g || g.status === "finished" ? (
        <>
          {g?.status === "finished" && (
            <Card accent="ok">
              {g.score > g.total / 2 || g.experts > g.viewers ? <Confetti /> : null}
              <div className={s.center}><Asset id={g.score > g.total / 2 || g.experts > g.viewers ? "result.win" : "result.lose"} fallback="🏁" size={140} /></div>
              <h2>Игра окончена 🏁</h2>
              <p className={s.dim}>{g.mode === "wheel" ? `Знатоки ${g.experts} : ${g.viewers} телезрители` : `Очков: ${g.score} из ${g.total}`}</p>
              {g.log?.map((r, i) => <p key={i} className={s.step}>{i + 1}. {r.level === "correct" ? "✅" : r.level === "close" ? "🟡" : "❌"} {r.answer ?? "— нет ответа"}</p>)}
            </Card>
          )}
          <Card><h2>Новая игра</h2><p className={s.dim}>Выбери формат ниже — кто запустит игру, тот и капитан.</p></Card>
          <Button disabled={!online} onClick={() => send({ type: "start", mode: "sport", tours: 3, per_tour: 12 })}>Спортивное ЧГК · 3 тура по 12</Button>
          <Button disabled={!online} variant="ghost" onClick={() => send({ type: "start", mode: "sport", tours: 1, per_tour: 6 })}>Короткая · 6 вопросов</Button>
          <Button disabled={!online} variant="ghost" onClick={() => send({ type: "start", mode: "wheel" })}>🎡 Классический волчок</Button>
          <MenuButton variant="ghost" />
        </>
      ) : (
        <>
          {header}
          {g.mode === "wheel" && (
            <div className={s.center}>
              <Wheel n={g.total} played={g.played} spin={g.spin} spinKey={g.idx} onSettled={() => setOpened(true)} />
            </div>
          )}
          {wheelWait && g.spin && <div className={s.center}><Envelope sector={g.spin.sector} open={false} /></div>}
          {!wheelWait && (g.phase === "think" || g.phase === "answer") && (
            <div className={s.center}>
              <TimerRing deadlineMs={g.deadline_ms} offsetMs={offset} totalSec={g.phase === "think" ? g.think : 20} />
              <p className={s.dim}>{g.phase === "think" ? "Обсуждаем" : "Время сдавать ответ!"}</p>
            </div>
          )}
          {g.phase === "review" && g.verdict && (
            <Card accent={ACCENT[g.verdict.level]}>
              <VerdictBadge level={g.verdict.level} timeout={g.verdict.source === "timeout"}
                comment={`Ответ команды: ${g.answer ?? "— не успели"}. ${g.verdict.comment}`}
                extra={g.verdict.disputed ? "⚠️ Судья не ответил — решает капитан." : g.verdict.overridden ? "Решение капитана" : undefined} />
            </Card>
          )}
          {g.question && !wheelWait && (
            <QuestionCard key={g.idx} text={g.question.text} label={g.mode === "wheel" && g.spin ? `Сектор ${g.spin.sector + 1}` : "Вопрос"}
              flipped={g.phase === "review" && !!g.reveal}
              back={g.reveal && (
                <div>
                  <div style={{ fontFamily: "var(--font-display)", fontSize: 13, letterSpacing: ".14em", textTransform: "uppercase", color: "var(--gold)", textAlign: "center" }}>Ответ</div>
                  <h2 className="gold-text" style={{ textAlign: "center", margin: "8px 0 4px", fontSize: 28 }}>{g.reveal.answer}</h2>
                  <p className={s.explain}>{g.reveal.explanation}</p>
                </div>
              )} />
          )}
          <AnimatePresence mode="wait">
            <motion.div key={g.phase + g.idx} className={s.col} initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}>

              {!wheelWait && (g.phase === "think" || g.phase === "answer") && (isCaptain ? (
                <>
                  <input className={s.input} value={text} placeholder="Ответ команды" onChange={(e) => setText(e.target.value)} />
                  <Button disabled={!text.trim()} onClick={() => send({ type: "answer", text })}>Сдать ответ</Button>
                </>
              ) : <p className={s.dim}>Ответ сдаёт капитан.</p>)}

              {g.phase === "judging" && <p className={s.dim}>Ответ «{g.answer}» — судья думает…</p>}

              {g.phase === "review" && g.verdict && (
                <>
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
          {isCaptain && room && room.players.length > 1 && (
            <Button variant="ghost" onClick={() => {
              const others = room.players.filter((p) => p.id !== me?.user.id);
              const i = others.findIndex((p) => p.id === g.captain_id);
              send({ type: "captain", user_id: others[(i + 1) % others.length].id });
            }}>Передать капитанство →</Button>
          )}
          {isCaptain && <Button variant="ghost" onClick={() => send({ type: "stop" })}>Закончить игру</Button>}
        </>
      )}
    </div>
  );
}
