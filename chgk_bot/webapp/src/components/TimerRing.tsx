import { useEffect, useRef, useState } from "react";
import { sound } from "../sound";
import { tg } from "../tg";

interface Props {
  deadlineMs: number;      // серверный дедлайн
  offsetMs: number;        // server_now - Date.now() на момент ответа сервера
  totalSec: number;
  onEnd?: () => void;
}

/** Кольцо-таймер: время берём от серверного дедлайна, поэтому «подкрутить» часы на телефоне нельзя. */
export function TimerRing({ deadlineMs, offsetMs, totalSec, onEnd }: Props) {
  const left = () => Math.max(0, deadlineMs - (Date.now() + offsetMs));
  const [ms, setMs] = useState(left);
  const lastTick = useRef(-1);

  useEffect(() => {
    let raf = 0;
    let done = false;
    const tick = () => {
      const v = left();
      setMs(v);
      if (v <= 0) {
        if (!done) { done = true; onEnd?.(); }
        return;
      }
      raf = requestAnimationFrame(tick);
    };
    tick();
    return () => cancelAnimationFrame(raf);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [deadlineMs, offsetMs]);

  const R = 52, C = 2 * Math.PI * R;
  const frac = Math.min(1, ms / (totalSec * 1000));
  const sec = Math.ceil(ms / 1000);
  const hot = sec <= 10;
  useEffect(() => {
    if (hot && sec > 0 && sec !== lastTick.current) { lastTick.current = sec; sound.play(sec === 10 ? "timer10" : "tick"); if (sec <= 3) tg.haptic("medium"); }
  }, [sec, hot]);
  return (
    <svg className="timer-ring" width="132" height="132" viewBox="0 0 132 132" aria-label={`Осталось ${sec} с`}>
      <circle cx="66" cy="66" r={R} fill="none" stroke="rgba(255,255,255,.1)" strokeWidth="10" />
      <circle
        cx="66" cy="66" r={R} fill="none" strokeWidth="10" strokeLinecap="round"
        stroke={hot ? "var(--bad)" : "var(--gold)"}
        strokeDasharray={C} strokeDashoffset={C * (1 - frac)}
        transform="rotate(-90 66 66)"
      />
      <text x="66" y="66" textAnchor="middle" dominantBaseline="central" fill="var(--text)" fontSize="38" fontWeight="700">
        {sec}
      </text>
    </svg>
  );
}
