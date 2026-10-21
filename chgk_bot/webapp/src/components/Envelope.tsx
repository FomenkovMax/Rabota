import { motion } from "framer-motion";
import { Asset } from "./Asset";
import { useEffect } from "react";
import { sound } from "../sound";

/** Конверт волчка: «выезжает», открывается и отдаёт место вопросу. Графика — wheel.envelope.closed / .open. */
export function Envelope({ sector, open, onOpened }: { sector: number; open: boolean; onOpened?: () => void }) {
  useEffect(() => {
    if (!open) return;
    const t = setTimeout(() => onOpened?.(), 700);
    return () => clearTimeout(t);
  }, [open, onOpened]);
  return (
    <motion.div initial={{ y: 60, opacity: 0, scale: 0.8 }} animate={{ y: 0, opacity: 1, scale: open ? 1.15 : 1 }}
      transition={{ type: "spring", stiffness: 160, damping: 16 }}
      style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 6 }}>
      <motion.div animate={open ? { rotate: [0, -6, 6, 0] } : {}} transition={{ duration: 0.5 }}>
        {open ? <Asset id="wheel.envelope.open" fallback="📨" size={110} /> : <Asset id="wheel.envelope.closed" fallback="✉️" size={110} />}
      </motion.div>
      <b style={{ color: "var(--gold-2)" }}>Сектор {sector + 1}</b>
    </motion.div>
  );
}
