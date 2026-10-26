import { motion } from "framer-motion";
import { Avatar } from "./Avatar";

interface Row { user_id: number; name: string; photo?: string; points: number; rank: number }
const H = { 1: 112, 2: 82, 3: 62 } as Record<number, number>;
const MEDAL = { 1: "🥇", 2: "🥈", 3: "🥉" } as Record<number, string>;

/** Пьедестал топ-3: ступени вырастают снизу, сверху аватарки с медалями. Порядок 2-1-3, как на настоящем. */
export function Podium({ rows, meId }: { rows: Row[]; meId?: number }) {
  const top = [rows[1], rows[0], rows[2]].filter(Boolean) as Row[];
  return (
    <div style={{ display: "flex", alignItems: "flex-end", justifyContent: "center", gap: 8, paddingTop: 30 }}>
      {top.map((r) => (
        <div key={r.user_id} style={{ display: "flex", flexDirection: "column", alignItems: "center", width: 96 }}>
          <motion.div initial={{ opacity: 0, y: 14 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.35 + (3 - r.rank) * 0.12 }}
            style={{ display: "flex", flexDirection: "column", alignItems: "center", marginBottom: 6 }}>
            <Avatar id={r.user_id} name={r.name} photo={r.photo} size={r.rank === 1 ? 58 : 46} crown={r.rank === 1} />
            <span style={{ marginTop: 4, fontSize: 13, maxWidth: 92, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
              color: r.user_id === meId ? "var(--gold-2)" : "var(--text)" }}>{r.name}</span>
            <span style={{ fontSize: 12, color: "var(--text-dim)" }}>{r.points} очк.</span>
          </motion.div>
          <motion.div initial={{ scaleY: 0 }} animate={{ scaleY: 1 }} transition={{ delay: 0.1 + (3 - r.rank) * 0.1, type: "spring", stiffness: 120, damping: 16 }}
            style={{ transformOrigin: "bottom", width: "100%", height: H[r.rank], borderRadius: "10px 10px 4px 4px",
              background: r.rank === 1 ? "linear-gradient(180deg, #2c3d7c, #16224a)" : "linear-gradient(180deg, #24336a, #131d40)",
              border: "1px solid rgba(242,184,75,.45)", borderBottom: 0, boxShadow: r.rank === 1 ? "var(--glow-gold)" : "var(--shadow)",
              display: "flex", flexDirection: "column", alignItems: "center", paddingTop: 6 }}>
            <span style={{ fontSize: 26 }}>{MEDAL[r.rank]}</span>
            <span style={{ fontWeight: 800, fontSize: 18, background: "var(--gold-grad)", WebkitBackgroundClip: "text", backgroundClip: "text", color: "transparent" }}>{r.rank}</span>
          </motion.div>
        </div>
      ))}
    </div>
  );
}
