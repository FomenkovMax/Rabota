import { motion } from "framer-motion";

type Level = "correct" | "close" | "wrong";
const COLOR = { correct: "var(--ok)", close: "var(--half)", wrong: "var(--bad)" };
const TITLE = { correct: "Верно!", close: "Почти", wrong: "Мимо" };

/** Крупный значок вердикта: галочка рисуется линией, «почти» — пружинит, крестик — встряхивается. */
export function VerdictBadge({ level, timeout, comment, extra }: { level: Level; timeout?: boolean; comment?: string; extra?: string }) {
  const c = COLOR[level];
  const draw = { initial: { pathLength: 0 }, animate: { pathLength: 1 }, transition: { duration: 0.45, delay: 0.15, ease: "easeOut" as const } };
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
      <motion.div
        initial={{ scale: 0.4, opacity: 0 }}
        animate={level === "wrong" ? { scale: 1, opacity: 1, x: [0, -8, 8, -5, 5, 0] } : { scale: [0.4, 1.12, 1], opacity: 1 }}
        transition={{ duration: 0.55 }}
        style={{ flex: "0 0 auto", width: 72, height: 72, borderRadius: "50%", display: "grid", placeItems: "center",
          background: `radial-gradient(circle at 35% 30%, color-mix(in srgb, ${c} 55%, #fff 0%), ${c})`,
          boxShadow: `0 0 0 4px rgba(255,255,255,.08), 0 0 28px color-mix(in srgb, ${c} 60%, transparent)` }}>
        <svg width="40" height="40" viewBox="0 0 40 40" fill="none" stroke="#fff" strokeWidth="5" strokeLinecap="round" strokeLinejoin="round">
          {level === "correct" && <motion.path d="M9 21 L17 29 L31 12" {...draw} />}
          {level === "wrong" && <><motion.path d="M11 11 L29 29" {...draw} /><motion.path d="M29 11 L11 29" {...draw} /></>}
          {level === "close" && <motion.path d="M9 22 C 14 14, 20 30, 31 18" {...draw} />}
        </svg>
      </motion.div>
      <div>
        <h2 style={{ color: c }}>{timeout ? "Время вышло" : TITLE[level]}</h2>
        {comment && <p style={{ color: "var(--text-dim)", fontSize: 15, lineHeight: 1.4, marginTop: 2 }}>{comment}</p>}
        {extra && <p style={{ color: "var(--text-dim)", fontSize: 14, marginTop: 4 }}>{extra}</p>}
      </div>
    </div>
  );
}
