import { motion, useReducedMotion } from "framer-motion";
import { useState } from "react";
import { tg } from "../tg";
import { Asset } from "./Asset";

/** «Живая» сова на главной: парит, «дышит», за ней медленно вращаются золотые лучи. Нажатие — довольный взмах. */
export function OwlHero({ size = 132 }: { size?: number }) {
  const still = useReducedMotion();
  const [poke, setPoke] = useState(0);
  return (
    <div className="owl-hero" style={{ position: "relative", width: size * 1.9, height: size * 1.35, display: "flex", alignItems: "center", justifyContent: "center" }}>
      <motion.div aria-hidden
        animate={still ? {} : { rotate: 360 }} transition={{ duration: 40, repeat: Infinity, ease: "linear" }}
        style={{ position: "absolute", width: size * 1.8, height: size * 1.8, borderRadius: "50%", opacity: 0.55,
          background: "repeating-conic-gradient(from 0deg, rgba(255,217,130,.28) 0deg 6deg, transparent 6deg 22deg)",
          WebkitMaskImage: "radial-gradient(closest-side, #000 35%, transparent 72%)", maskImage: "radial-gradient(closest-side, #000 35%, transparent 72%)" }} />
      <motion.div aria-hidden animate={still ? {} : { opacity: [0.35, 0.7, 0.35], scale: [0.95, 1.05, 0.95] }}
        transition={{ duration: 4, repeat: Infinity, ease: "easeInOut" }}
        style={{ position: "absolute", width: size * 1.1, height: size * 1.1, borderRadius: "50%", background: "radial-gradient(closest-side, rgba(242,184,75,.45), transparent)" }} />
      <motion.div key={poke}
        animate={still ? {} : poke ? { rotate: [0, -8, 8, -4, 0], scale: [1, 1.08, 1] } : { y: [0, -7, 0], scale: [1, 1.015, 1] }}
        transition={poke ? { duration: 0.6 } : { duration: 3.2, repeat: Infinity, ease: "easeInOut" }}
        onAnimationComplete={() => poke && setPoke(0)}
        onClick={() => { tg.haptic("medium"); setPoke(Date.now()); }}
        style={{ position: "relative", cursor: "pointer" }}>
        <Asset id="home.logo" fallback="🦉" size={size} />
      </motion.div>
    </div>
  );
}
