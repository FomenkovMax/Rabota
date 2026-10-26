import type { ReactNode } from "react";
import { Asset } from "./Asset";

/** Красивый пустой экран: сова + заголовок + подсказка (+ кнопка действия). */
export function EmptyState({ asset = "loader", fallback = "🦉", title, text, action }: { asset?: string; fallback?: string; title: string; text?: string; action?: ReactNode }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", textAlign: "center", gap: 8, padding: "10px 6px" }}>
      <div style={{ opacity: 0.9 }}><Asset id={asset} fallback={fallback} size={72} /></div>
      <b style={{ fontFamily: "var(--font-display)", fontWeight: 400, fontSize: 18 }}>{title}</b>
      {text && <p style={{ color: "var(--text-dim)", fontSize: 14, lineHeight: 1.4, margin: 0 }}>{text}</p>}
      {action && <div style={{ width: "100%", marginTop: 6 }}>{action}</div>}
    </div>
  );
}
