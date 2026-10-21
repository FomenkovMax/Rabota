import { useEffect } from "react";
import { Asset } from "./components/Asset";
import { Card } from "./components/Card";
import { Studio } from "./components/Studio";
import { Home } from "./screens/Home";
import { Admin } from "./screens/Admin";
import { Season } from "./screens/Season";
import { Solo } from "./screens/Solo";
import { Stats } from "./screens/Stats";
import { Team } from "./screens/Team";
import { useApp } from "./store";
import { tg } from "./tg";

export function App() {
  const { me, error, screen, boot } = useApp();
  useEffect(() => { tg.init(); void boot(); }, [boot]);

  let body;
  if (error) body = <div style={{ padding: 16 }}><Card accent="bad">{error}</Card></div>;
  else if (!me) body = <div style={{ padding: 24, textAlign: "center", color: "var(--text-dim)" }}><Asset id="loader" fallback="🦉" size={96} /><p>Загрузка…</p></div>;
  else body = screen === "solo" ? <Solo /> : screen === "team" ? <Team /> : screen === "stats" ? <Stats /> : screen === "season" ? <Season /> : screen === "admin" ? <Admin /> : <Home />;
  return <><Studio />{body}</>;
}
