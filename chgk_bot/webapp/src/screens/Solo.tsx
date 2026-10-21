import { AnimatePresence, motion } from "framer-motion";
import { useEffect, useRef, useState } from "react";
import { api, type AnswerResult, type Round, type Steps } from "../api";
import { Button } from "../components/Button";
import { Card } from "../components/Card";
import { TimerRing } from "../components/TimerRing";
import { useApp } from "../store";
import { sound } from "../sound";
import { tg } from "../tg";
import { Confetti } from "../components/Confetti";
import s from "./Screen.module.css";

type Phase = "loading" | "think" | "judging" | "result" | "error";
const LABEL = { correct: "Верно! 🎉", close: "Почти 🤏", wrong: "Мимо" } as const;
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

  return (
    <div className={s.wrap}>
      <AnimatePresence mode="wait">
        <motion.div key={phase + (round?.round_id ?? "")} className={s.col}
          initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}>
          {phase === "loading" && <p className={s.dim}>Достаю вопрос…</p>}
          {phase === "error" && (<><Card accent="bad">{err}</Card><Button onClick={() => go("home")}>В меню</Button></>)}

          {(phase === "think" || phase === "judging") && round && (
            <>
              <div className={s.center}>
                <TimerRing deadlineMs={round.deadline_ms} offsetMs={offset} totalSec={round.think_seconds}
                  onEnd={() => { if (phase === "think") tg.haptic("heavy"); }} />
              </div>
              <Card><p className={s.question}>{round.question.text}</p></Card>
              <input className={s.input} value={text} placeholder="Твой ответ" disabled={phase === "judging"}
                onChange={(e) => setText(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter" && text.trim()) void send(text); }} />
              <Button disabled={phase === "judging" || !text.trim()} onClick={() => void send(text)}>
                {phase === "judging" ? "Судья думает…" : "Ответить"}
              </Button>
              <Button variant="ghost" disabled={phase === "judging"} onClick={() => void skip()}>Не знаю</Button>
            </>
          )}

          {phase === "result" && res && (
            <>
              {res.verdict.level === "correct" && <Confetti />}
              <Card accent={ACCENT[res.verdict.level]}>
                <h2>{res.timeout ? "Время вышло ⏰" : LABEL[res.verdict.level]}</h2>
                <p className={s.dim}>{res.verdict.comment}</p>
                {res.verdict.disputed && <p className={s.dim}>⚠️ Судья не ответил — решение спорное.</p>}
              </Card>
              <Card>
                <p className={s.dim}>Ответ</p>
                <h2>{res.reveal.answer}</h2>
                {res.reveal.accept_note && <p className={s.dim}>{res.reveal.accept_note}</p>}
                <p className={s.explain}>{res.reveal.explanation}</p>
                {res.reveal.source && <p className={s.dim}>Источник: {res.reveal.source}</p>}
              </Card>
              {steps === undefined && <Button variant="ghost" onClick={() => void loadSteps()}>🧩 Разбор по шагам</Button>}
              {steps === null && <p className={s.dim}>Составляю разбор…</p>}
              {steps && (
                <Card>
                  {steps.steps.map((st, i) => (
                    <p key={i} className={s.step}>
                      <b>{i + 1}.</b> {st.clue && <i>«{st.clue}» → </i>}{st.inference}
                    </p>
                  ))}
                  {steps.lesson && <p className={s.explain}>💡 {steps.lesson}</p>}
                </Card>
              )}
              <Button onClick={() => void next()}>Следующий вопрос</Button>
              <Button variant="ghost" onClick={() => go("home")}>В меню</Button>
            </>
          )}
        </motion.div>
      </AnimatePresence>
    </div>
  );
}
