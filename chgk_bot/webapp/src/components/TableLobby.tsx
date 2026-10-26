import { motion } from "framer-motion";
import { Asset } from "./Asset";
import { Avatar } from "./Avatar";

interface P { id: number; name: string; photo?: string }

/** «Стол знатоков»: игроки рассаживаются по кругу вокруг стола; пустые места — до 6, чтобы стол не выглядел пустым. */
export function TableLobby({ players, captainId, meId }: { players: P[]; captainId?: number; meId?: number }) {
  const seats = Math.max(6, players.length);
  const R = 132, C = 160;
  return (
    <div style={{ position: "relative", width: 320, height: 320, margin: "0 auto" }}>
      <div style={{ position: "absolute", left: C - 92, top: C - 92, width: 184, height: 184, filter: "drop-shadow(0 12px 24px rgba(0,0,0,.55))" }}>
        <Asset id="wheel.table" fallback="🎡" size={184} />
      </div>
      {Array.from({ length: seats }, (_, i) => {
        const a = (i / seats) * 2 * Math.PI - Math.PI / 2;
        const p = players[i];
        const x = C + R * Math.cos(a), y = C + R * Math.sin(a);
        return (
          <motion.div key={p ? p.id : `empty${i}`} initial={{ scale: 0, opacity: 0 }} animate={{ scale: 1, opacity: 1 }}
            transition={{ delay: i * 0.05, type: "spring", stiffness: 260, damping: 18 }}
            style={{ position: "absolute", left: x - 24, top: y - 24, width: 48, display: "flex", flexDirection: "column", alignItems: "center" }}>
            {p ? (
              <>
                <Avatar id={p.id} name={p.name} photo={p.photo} size={48} crown={p.id === captainId} />
                <span style={{ marginTop: 3, fontSize: 11, maxWidth: 76, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
                  color: p.id === meId ? "var(--gold-2)" : "var(--text-dim)" }}>{p.id === meId ? "ты" : p.name}</span>
              </>
            ) : (
              <span style={{ width: 48, height: 48, borderRadius: "50%", border: "2px dashed rgba(242,184,75,.25)", background: "rgba(10,16,36,.5)" }} />
            )}
          </motion.div>
        );
      })}
    </div>
  );
}
