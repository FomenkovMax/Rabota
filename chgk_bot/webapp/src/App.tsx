import { useEffect } from "react";
import { Card } from "./components/Card";
import { Studio } from "./components/Studio";
import { Home } from "./screens/Home";
import { Solo } from "./screens/Solo";
import { Team } from "./screens/Team";
import { useApp } from "./store";
import { tg } from "./tg";

export function App() {
  const { me, error, screen, boot } = useApp();
  useEffect(() => { tg.init(); void boot(); }, [boot]);

  let body;
  if (error) body = <div style={{ padding: 16 }}><Card accent="bad">{error}</Card></div>;
  else if (!me) body = <div style={{ padding: 24, textAlign: "center", color: "var(--text-dim)" }}>Загрузка…</div>;
  else body = screen === "solo" ? <Solo /> : screen === "team" ? <Team /> : <Home />;
  return <><Studio />{body}</>;
}
