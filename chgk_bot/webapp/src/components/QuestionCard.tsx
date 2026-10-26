import { motion } from "framer-motion";
import type { ReactNode } from "react";
import s from "./QuestionCard.module.css";

/** Карточка вопроса «из конверта»: лицо — бумага с вопросом, оборот — ответ. flipped переворачивает её (rotateY).
 *  Обе стороны лежат в одной ячейке сетки, поэтому высота карточки = высоте большей стороны. */
export function QuestionCard({ text, flipped, back, label }: { text: string; flipped: boolean; back?: ReactNode; label?: string }) {
  return (
    <motion.div className={s.scene} initial={{ y: 30, opacity: 0, rotateX: 12 }} animate={{ y: 0, opacity: 1, rotateX: 0 }}
      transition={{ type: "spring", stiffness: 140, damping: 18 }}>
      <motion.div className={s.card} animate={{ rotateY: flipped ? 180 : 0 }} transition={{ duration: 0.7, ease: [0.3, 0.7, 0.2, 1] }}>
        <div className={`${s.face} ${s.front}`}>
          {label && <div className={s.label}>{label}</div>}
          <p className={s.text}>{text}</p>
        </div>
        <div className={`${s.face} ${s.back}`}>{back}</div>
      </motion.div>
    </motion.div>
  );
}
