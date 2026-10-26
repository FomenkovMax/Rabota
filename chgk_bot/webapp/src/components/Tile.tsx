import { motion } from "framer-motion";
import { tg } from "../tg";
import { Asset } from "./Asset";
import s from "./Tile.module.css";

interface Props { id: string; fallback: string; title: string; sub?: string; accent?: boolean; delay?: number; onClick: () => void }

/** Плитка главного меню: иллюстрация по ID ассета + подпись. Появляется «волной», при нажатии пружинит. */
export function Tile({ id, fallback, title, sub, accent, delay = 0, onClick }: Props) {
  return (
    <motion.button className={`${s.tile} ${accent ? s.accent : ""}`}
      initial={{ opacity: 0, y: 18, scale: 0.96 }} animate={{ opacity: 1, y: 0, scale: 1 }}
      transition={{ delay, type: "spring", stiffness: 220, damping: 20 }}
      whileTap={{ scale: 0.95 }}
      onClick={() => { tg.haptic("light"); onClick(); }}>
      <span className={s.art}><Asset id={id} fallback={fallback} size={92} /></span>
      <span className={s.title}>{title}</span>
      {sub && <span className={s.sub}>{sub}</span>}
    </motion.button>
  );
}
