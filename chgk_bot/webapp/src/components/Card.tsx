import type { ReactNode } from "react";
import s from "./Card.module.css";

export function Card({ children, accent }: { children: ReactNode; accent?: "ok" | "bad" | "half" }) {
  return <div className={`${s.card} ${accent ? s[accent] : ""}`}>{children}</div>;
}
