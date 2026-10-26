import { AnimatePresence, motion } from "framer-motion";
import s from "./Scoreboard.module.css";

/** Цифра табло: при смене значения старая уезжает вверх, новая въезжает снизу. */
function Digit({ v }: { v: string | number }) {
  return (
    <span className={s.digitBox}>
      <AnimatePresence mode="popLayout" initial={false}>
        <motion.span key={String(v)} className={s.digit} initial={{ y: "70%", opacity: 0 }} animate={{ y: 0, opacity: 1 }} exit={{ y: "-70%", opacity: 0 }}
          transition={{ type: "spring", stiffness: 260, damping: 22 }}>{v}</motion.span>
      </AnimatePresence>
    </span>
  );
}

export interface Cell { label: string; value: string | number; hot?: boolean }

/** Табло счёта в стиле студии: 2–3 ячейки, подписи капителью, золотые цифры. */
export function Scoreboard({ cells, sep, caption }: { cells: Cell[]; sep?: string; caption?: string }) {
  return (
    <div className={s.board}>
      <div className={s.row}>
        {cells.map((c, i) => (
          <div key={c.label} style={{ display: "contents" }}>
            {i > 0 && <span className={s.sep}>{sep ?? ""}</span>}
            <div className={`${s.cell} ${c.hot ? s.hot : ""}`}>
              <Digit v={c.value} />
              <span className={s.label}>{c.label}</span>
            </div>
          </div>
        ))}
      </div>
      {caption && <div className={s.caption}>{caption}</div>}
    </div>
  );
}
