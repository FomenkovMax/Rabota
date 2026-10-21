import { useEffect } from "react";
import { Card } from "./components/Card";
import { Home } from "./screens/Home";
import { Solo } from "./screens/Solo";
import { useApp } from "./store";
import { tg } from "./tg";

export function App() {
  const { me, error, screen, boot } = useApp();
  useEffect(() => { tg.init(); void boot(); }, [boot]);
  if (error) return <div style={{ padding: 16 }}><Card accent="bad">{error}</Card></div>;
  if (!me) return <div style={{ padding: 24, textAlign: "center", color: "var(--text-dim)" }}>Загрузка…</div>;
  return screen === "solo" ? <Solo /> : <Home />;
}
