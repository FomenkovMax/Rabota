import { animate } from "framer-motion";
import { useEffect, useRef, useState } from "react";

interface Props {
  n: number;
  played: number[];          // включая текущий выпавший
  spin: { sector: number; turns: number; duration_ms: number; offset: number } | null;
  spinKey: number;           // меняется на каждый новый бросок
  onSettled?: () => void;
}

/** Волчок: стрелка вращается к сектору, который выбрал СЕРВЕР; клиент только рисует. Игра: ID wheel.table / wheel.arrow подменят графику. */
export function Wheel({ n, played, spin, spinKey, onSettled }: Props) {
  const [angle, setAngle] = useState(0);
  const [settled, setSettled] = useState(true);
  const base = useRef(0);
  const step = 360 / n;

  useEffect(() => {
    if (!spin) return;
    setSettled(false);
    const target = spin.turns * 360 + (spin.sector + 0.5 + spin.offset) * step;
    const from = base.current % 360;
    const ctl = animate(from, from + target, {
      duration: spin.duration_ms / 1000,
      ease: [0.12, 0.7, 0.1, 1],       // быстрый разгон и плавное торможение
      onUpdate: setAngle,
      onComplete: () => { base.current = (from + target) % 360; setSettled(true); onSettled?.(); },
    });
    return () => ctl.stop();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [spinKey]);

  const current = spin?.sector;
  const R = 150, C = 160;
  const pt = (deg: number, r: number) => {
    const a = ((deg - 90) * Math.PI) / 180;
    return [C + r * Math.cos(a), C + r * Math.sin(a)];
  };
  return (
    <svg viewBox="0 0 320 320" width="100%" style={{ maxWidth: 320 }}>
      {Array.from({ length: n }, (_, i) => {
        const [x1, y1] = pt(i * step, R), [x2, y2] = pt((i + 1) * step, R), [tx, ty] = pt((i + 0.5) * step, R * 0.72);
        const done = played.includes(i) && !(i === current && !settled);
        const hot = i === current && settled;
        return (
          <g key={i}>
            <path d={`M${C},${C} L${x1},${y1} A${R},${R} 0 0 1 ${x2},${y2} Z`}
              fill={hot ? "var(--gold)" : done ? "#0e1631" : i % 2 ? "var(--surface)" : "var(--surface-2)"}
              stroke="var(--bg)" strokeWidth="2" />
            <text x={tx} y={ty} textAnchor="middle" dominantBaseline="central" fontSize="16" fontWeight="700"
              fill={hot ? "#2a1d00" : done ? "#3a4670" : "var(--text)"}>{i + 1}</text>
          </g>
        );
      })}
      <circle cx={C} cy={C} r="18" fill="var(--gold)" />
      <g transform={`rotate(${angle} ${C} ${C})`}>
        <polygon points={`${C},${C - R + 6} ${C - 9},${C - 24} ${C + 9},${C - 24}`} fill="var(--bad)" stroke="#fff" strokeWidth="1.5" />
      </g>
    </svg>
  );
}
