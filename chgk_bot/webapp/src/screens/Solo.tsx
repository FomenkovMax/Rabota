import { AnimatePresence, motion } from "framer-motion";
import { useEffect, useRef, useState } from "react";
import { api, type AnswerResult, type Round, type Steps } from "../api";
import { Asset } from "../components/Asset";
import { Button } from "../components/Button";
import { MenuButton } from "../components/MenuButton";
import { Card } from "../components/Card";
import { TimerRing } from "../components/TimerRing";
import { useApp } from "../store";
import { sound } from "../sound";
import { tg } from "../tg";
import { Confetti } from "../components/Confetti";
import { QuestionCard } from "../components/QuestionCard";
import { VerdictBadge } from "../components/VerdictBadge";
import s from "./Screen.module.css";

type Phase = "loading" | "think" | "judging" | "result" | "error";
const ACCENT = { correct: "ok", close: "half", wrong: "bad" } as const;

export function Solo() {
  const { go, refresh } = useApp();
  const [phase, setPhase] = useState<Phase>("loading");
  const [round, setRound] = useState<Round | null>(null);
  const [offset, setOffset] = useState(0);
  const [text, setText] = useState("");
  const [res, setRes] = useState<AnswerResult | null>(null);
  const [steps, setSteps] = useState<Steps | null | undefined>(undefined);
  const [err, setErr] = useState("");
  const busy = useRef(false);

  async function next() {
    setPhase("loading"); setText(""); setRes(null); setSteps(undefined);
    try {
      const r = await api.next();
      setOffset(r.server_now_ms - Date.now());
      setRound(r);
      setPhase("think");
    } catch (e) { setErr((e as Error).message); setPhase("error"); }
  }
  useEffect(() => { void next(); }, []);

  async function send(answer: string) {
    if (!round || busy.current) return;
    busy.current = true;
    setPhase("judging");
    try {
      const r = await api.answer(round.round_id, answer);
      setRes(r);
      tg.haptic(r.verdict.level === "correct" ? "success" : r.verdict.level === "wrong" ? "error" : "medium");
      sound.play(r.verdict.level === "wrong" ? "fail" : "ok");
      setPhase("result");
      void refresh();
    } catch (e) { setErr((e as Error).message); setPhase("error"); }
    busy.current = false;
  }

  async function skip() {
    if (!round || busy.current) return;
    busy.current = true;
    try {
      const r = await api.skip(round.round_id);
      setRes({ timeout: false, verdict: { level: "wrong", score: 0, comment: "Вопрос пропущен.", source: "skip", disputed: false }, reveal: r.reveal });
      setPhase("result");
      void refresh();
    } catch (e) { setErr((e as Error).message); setPhase("error"); }
    busy.current = false;
  }

  async function loadSteps() {
    if (!round) return;
    setSteps(null);
    try { setSteps((await api.steps(round.question.id)).steps); } catch { setSteps(undefined); }
  }

  const showCard = round && (phase === "think" || phase === "judging" || phase === "result");
  return (
    <div className={s.wrap}>
      {phase === "loading" && (
        <div className={s.center} style={{ minHeight: "50vh", justifyContent: "center" }}>
          <motion.div animate={{ y: [0, -10, 0], rotate: [0, -4, 4, 0] }} transition={{ duration: 1.4, repeat: Infinity, ease: "easeInOut" }}>
            <Asset id="wheel.envelope.closed" fallback="✉️" size={120} />
          </motion.div>
          <p className={s.dim}>Достаю конверт…</p>
        </div>
      )}
      {phase === "error" && (<><Card accent="bad">{err}</Card><Button onClick={() => go("home")}>В меню</Button></>)}

      {showCard && (
        <>
          {phase !== "result" ? (
            <div className={s.center}>
              <TimerRing deadlineMs={round.deadline_ms} offsetMs={offset} totalSec={round.think_seconds}
                onEnd={() => { if (phase === "think") tg.haptic("heavy"); }} />
            </div>
          ) : res && (
            <motion.div initial={{ opacity: 0, y: -10 }} animate={{ opacity: 1, y: 0 }}>
              {res.verdict.level === "correct" && <Confetti />}
              <Card accent={ACCENT[res.verdict.level]}>
                <VerdictBadge level={res.verdict.level} timeout={res.timeout} comment={res.verdict.comment}
                  extra={res.verdict.disputed ? "⚠️ Судья не ответил — решение спорное." : undefined} />
              </Card>
            </motion.div>
          )}

          {/* карточка остаётся на месте между фазами — поэтому переворот анимируется */}
          <QuestionCard key={round.round_id} text={round.question.text} label="Вопрос" flipped={phase === "result"}
            back={res && (
              <div>
                <div style={{ fontFamily: "var(--font-display)", fontSize: 13, letterSpacing: ".14em", textTransform: "uppercase", color: "var(--gold)", textAlign: "center" }}>Ответ</div>
                <h2 className="gold-text" style={{ textAlign: "center", margin: "8px 0 4px", fontSize: 28 }}>{res.reveal.answer}</h2>
                {res.reveal.accept_note && <p className={s.dim} style={{ textAlign: "center" }}>{res.reveal.accept_note}</p>}
                <p className={s.explain}>{res.reveal.explanation}</p>
                {res.reveal.source && <p className={s.dim} style={{ marginTop: 10, fontSize: 13 }}>Источник: {res.reveal.source}</p>}
              </div>
            )} />

          {phase !== "result" ? (
            <>
              <input className={s.input} value={text} placeholder="Твой ответ" disabled={phase === "judging"}
                onChange={(e) => setText(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter" && text.trim()) void send(text); }} />
              <Button disabled={phase === "judging" || !text.trim()} onClick={() => void send(text)}>
                {phase === "judging" ? "Судья думает…" : "Ответить"}
              </Button>
              <Button variant="ghost" disabled={phase === "judging"} onClick={() => void skip()}>Не знаю</Button>
            </>
          ) : res && (
            <AnimatePresence>
              <motion.div className={s.col} initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: 0.5 }}>
                {res.new_achievements?.map((a) => (
                  <motion.div key={a.code} initial={{ scale: 0.8, opacity: 0 }} animate={{ scale: 1, opacity: 1 }}>
                    <Card accent="ok"><div className={s.row}><Asset id={`ach.${a.code}`} fallback={a.icon} size={52} /><div><b>Ачивка: {a.name}</b><p className={s.dim}>{a.desc}</p></div></div></Card>
                  </motion.div>
                ))}
                {steps === undefined && <Button variant="ghost" onClick={() => void loadSteps()}>🧩 Разбор по шагам</Button>}
                {steps === null && <p className={s.dim}>Составляю разбор…</p>}
                {steps && (
                  <Card>
                    {steps.steps.map((st, i) => (
                      <motion.p key={i} className={s.step} initial={{ opacity: 0, x: -8 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: i * 0.12 }}>
                        <b>{i + 1}.</b> {st.clue && <i>«{st.clue}» → </i>}{st.inference}
                      </motion.p>
                    ))}
                    {steps.lesson && <p className={s.explain}>💡 {steps.lesson}</p>}
                  </Card>
                )}
                <Button onClick={() => void next()}>Следующий вопрос</Button>
                <MenuButton variant="ghost" />
              </motion.div>
            </AnimatePresence>
          )}
        </>
      )}
    </div>
  );
}
