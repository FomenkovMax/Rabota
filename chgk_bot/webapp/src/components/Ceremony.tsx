import { AnimatePresence, motion } from "framer-motion";
import { Button } from "./Button";
import { Confetti } from "./Confetti";

/** Сцена вручения награды: видео award.ceremony.mp4 (без звука, автозапуск) поверх экрана. Нет файла — просто карточка с подписью. */
export function Ceremony({ title, subtitle, onClose }: { title: string; subtitle: string; onClose: () => void }) {
  return (
    <AnimatePresence>
      <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
        style={{ position: "fixed", inset: 0, zIndex: 20, background: "#05080f", display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "flex-end" }}>
        <video src="/assets/award.ceremony.mp4" poster="/assets/award.ceremony.poster.webp" autoPlay muted playsInline loop
          style={{ position: "absolute", inset: 0, width: "100%", height: "100%", objectFit: "cover" }} />
        <Confetti />
        <div style={{ position: "relative", width: "100%", maxWidth: 520, padding: "0 16px calc(24px + env(safe-area-inset-bottom))", display: "flex", flexDirection: "column", gap: 12, textAlign: "center",
          background: "linear-gradient(transparent, rgba(5,8,15,.85) 40%)" , paddingTop: 80 }}>
          <h1 style={{ color: "var(--gold-2)", textShadow: "0 2px 12px #000" }}>{title}</h1>
          <p style={{ color: "var(--text)", textShadow: "0 2px 8px #000" }}>{subtitle}</p>
          <Button onClick={onClose}>Принять награду</Button>
        </div>
      </motion.div>
    </AnimatePresence>
  );
}
