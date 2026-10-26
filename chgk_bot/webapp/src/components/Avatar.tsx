import { useState } from "react";

const HUES = [210, 35, 160, 280, 0, 190, 120, 320];

/** Аватарка игрока: фото из Telegram в золотом кольце; нет фото — инициалы на цветном фоне (цвет от id). */
export function Avatar({ id, name, photo, size = 44, crown, dim }: { id: number; name: string; photo?: string; size?: number; crown?: boolean; dim?: boolean }) {
  const [broken, setBroken] = useState(false);
  const initials = name.split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0]).join("").toUpperCase() || "?";
  const hue = HUES[Math.abs(id) % HUES.length];
  return (
    <span style={{ position: "relative", display: "inline-flex", width: size, height: size, flex: "0 0 auto", opacity: dim ? 0.45 : 1 }} title={name}>
      <span style={{ width: "100%", height: "100%", borderRadius: "50%", overflow: "hidden", display: "grid", placeItems: "center",
        border: `2px solid ${crown ? "var(--gold)" : "rgba(242,184,75,.45)"}`, boxShadow: crown ? "var(--glow-gold)" : "0 4px 10px rgba(0,0,0,.4)",
        background: `linear-gradient(145deg, hsl(${hue} 55% 42%), hsl(${hue} 60% 24%))`, color: "#fff", fontWeight: 700, fontSize: size * 0.38 }}>
        {photo && !broken ? <img src={photo} alt="" referrerPolicy="no-referrer" onError={() => setBroken(true)} style={{ width: "100%", height: "100%", objectFit: "cover" }} /> : initials}
      </span>
      {crown && <span style={{ position: "absolute", top: -size * 0.32, left: "50%", transform: "translateX(-50%)", fontSize: size * 0.42, filter: "drop-shadow(0 2px 3px rgba(0,0,0,.6))" }}>👑</span>}
    </span>
  );
}
