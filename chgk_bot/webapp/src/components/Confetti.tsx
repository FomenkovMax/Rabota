import { motion } from "framer-motion";
import { useMemo } from "react";

/** Конфетти для победы: 28 частиц, анимируются только transform/opacity. */
export function Confetti() {
  const parts = useMemo(() => Array.from({ length: 28 }, (_, i) => ({
    x: (Math.random() - 0.5) * 340, r: Math.random() * 720 - 360, d: 1.4 + Math.random() * 1.2,
    delay: Math.random() * 0.4, c: ["var(--gold)", "var(--gold-2)", "var(--ok)", "#fff", "var(--bad)"][i % 5], w: 6 + Math.random() * 6,
  })), []);
  return (
    <div style={{ position: "fixed", left: "50%", top: 0, pointerEvents: "none", zIndex: 5 }} aria-hidden>
      {parts.map((p, i) => (
        <motion.span key={i} style={{ position: "absolute", width: p.w, height: p.w * 1.6, background: p.c, borderRadius: 2 }}
          initial={{ y: -20, x: 0, opacity: 1, rotate: 0 }}
          animate={{ y: 700, x: p.x, opacity: 0, rotate: p.r }}
          transition={{ duration: p.d, delay: p.delay, ease: "easeIn" }} />
      ))}
    </div>
  );
}
