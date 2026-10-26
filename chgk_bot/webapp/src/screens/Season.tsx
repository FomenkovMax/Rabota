import { useEffect, useState } from "react";
import { api, type Season as SeasonT } from "../api";
import { Asset } from "../components/Asset";
import { Button } from "../components/Button";
import { MenuButton } from "../components/MenuButton";
import { Card } from "../components/Card";
import { CountUp } from "../components/CountUp";
import { Ceremony } from "../components/Ceremony";
import { useApp } from "../store";
import s from "./Screen.module.css";

const MONTHS = ["январь", "февраль", "март", "апрель", "май", "июнь", "июль", "август", "сентябрь", "октябрь", "ноябрь", "декабрь"];
const pretty = (k: string) => `${MONTHS[Number(k.slice(5)) - 1]} ${k.slice(0, 4)}`;

export function Season() {
  const { go, me } = useApp();
  const [d, setD] = useState<SeasonT | null>(null);
  const [err, setErr] = useState("");
  useEffect(() => { api.season().then(setD).catch((e) => setErr(e.message)); }, []);
  const [show, setShow] = useState<{ title: string; sub: string } | null>(null);
  // вручение: каждую свою награду показываем один раз (запоминаем в браузере), потом — по кнопке «🎬»
  useEffect(() => {
    if (!d || !me) return;
    const mine = d.awards.find((a) => {
      if (a.user_id !== me.user.id) return false;
      try { return !localStorage.getItem(`chgk.award.${a.season}.${a.kind}`); } catch { return false; }
    });
    if (mine) {
      const info = (me.brand as unknown as { awards: Record<string, { name: string }> }).awards?.[mine.kind];
      setShow({ title: info?.name ?? mine.kind, sub: `Победитель сезона ${pretty(mine.season)} — ${mine.points} очков` });
      try { localStorage.setItem(`chgk.award.${mine.season}.${mine.kind}`, "1"); } catch { /* ignore */ }
    }
  }, [d, me]);
  const brand = me?.brand as unknown as { awards: Record<string, { name: string; icon: string; desc: string }> } | undefined;

  return (
    <div className={s.wrap}>
      {show && <Ceremony title={show.title} subtitle={show.sub} onClose={() => setShow(null)} />}
      {err && <Card accent="bad">{err}</Card>}
      {!d && !err && <p className={s.dim}>Загружаю сезон…</p>}
      {d && (
        <>
          <Card>
            <div className={s.center}>
              <span style={{ fontSize: 56 }}>{d.me.league.icon}</span>
              <h2>{d.me.league.name}</h2>
              <p className={s.dim}>Сезон: {pretty(d.season)} · осталось дней: {d.days_left}</p>
            </div>
            <div className={s.stats} style={{ marginTop: 12 }}>
              <div><b><CountUp value={d.me.points} decimals={1} /></b><span>очков</span></div>
              <div><b>{d.me.rank ?? "—"}</b><span>место</span></div>
            </div>
            {d.me.next_league && <p className={s.dim} style={{ marginTop: 10 }}>До «{d.me.next_league.name}» {d.me.next_league.icon}: ещё {d.me.to_next} очк.</p>}
          </Card>

          <Card>
            <p className={s.dim}>Рейтинг сезона</p>
            {d.standings.length === 0 && <p className={s.step}>Пока никто не играл — стань первым!</p>}
            {d.standings.map((r) => (
              <p key={r.user_id} className={s.step}>
                <b>{r.rank}.</b> {r.name} — {r.points} очк. <span className={s.dim}>({Math.round(r.accuracy * 100)}%, {r.played} в.)</span>
              </p>
            ))}
          </Card>

          <Card>
            <p className={s.dim}>Награды сезонов</p>
            {d.awards.length === 0 && <p className={s.step}>Первые награды выдадим по итогам месяца.</p>}
            {d.awards.map((a, i) => {
              const info = brand?.awards?.[a.kind];
              return (
                <p key={i} className={s.step} style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <Asset id={`award.${a.kind === "owl" ? "owl" : "owl.diamond"}`} fallback={info?.icon ?? "🏅"} size={28} />
                  <span><b>{info?.name ?? a.kind}</b> — {a.name}, {pretty(a.season)}{a.user_id === me?.user.id && <button onClick={() => setShow({ title: info?.name ?? a.kind, sub: `Победитель сезона ${pretty(a.season)} — ${a.points} очков` })} style={{ marginLeft: 8, background: "none", border: 0, color: "var(--gold-2)", fontSize: 16 }} aria-label="Показать церемонию">🎬</button>}</span>
                </p>
              );
            })}
          </Card>

          <Card>
            <p className={s.dim}>Ачивки</p>
            {d.achievements.map((a) => (
              <p key={a.code} className={s.step} style={{ opacity: a.earned ? 1 : 0.45 }}>
                <span style={{ display: "inline-flex", verticalAlign: "middle", marginRight: 6, filter: a.earned ? "none" : "grayscale(1) brightness(.5)" }}><Asset id={`ach.${a.code}`} fallback={a.earned ? a.icon : "🔒"} size={36} /></span><b>{a.name}</b> — {a.desc}
              </p>
            ))}
          </Card>
        </>
      )}
      <MenuButton />
    </div>
  );
}
