import { useEffect, useState } from "react";
import { api, type AdminItem, type ImportReport } from "../api";
import { Button } from "../components/Button";
import { Card } from "../components/Card";
import { useApp } from "../store";
import s from "./Screen.module.css";

const EXAMPLE = `[{"text": "Текст вопроса", "answer": "Ответ", "explanation": "Разбор / комментарий автора", "accepted": ["вариант"], "tags": ["тема"]}]`;

export function Admin() {
  const { go } = useApp();
  const [q, setQ] = useState("");
  const [list, setList] = useState<{ total: number; items: AdminItem[] } | null>(null);
  const [msg, setMsg] = useState("");
  const [form, setForm] = useState({ text: "", answer: "", explanation: "" });
  const [fmt, setFmt] = useState<"json" | "csv">("json");
  const [content, setContent] = useState("");
  const [report, setReport] = useState<ImportReport | null>(null);

  const load = (query = q) => api.adminList(query).then(setList).catch((e) => setMsg(e.message));
  useEffect(() => { void load(""); }, []);

  async function run(fn: () => Promise<unknown>, ok: string) {
    try { await fn(); setMsg(ok); await load(); } catch (e) { setMsg((e as Error).message); }
  }

  return (
    <div className={s.wrap}>
      <h2>Вопросы{list ? `: ${list.total}` : ""}</h2>
      {msg && <Card>{msg}</Card>}

      <input className={s.input} placeholder="Поиск по тексту или ответу" value={q}
        onChange={(e) => { setQ(e.target.value); void load(e.target.value); }} />
      {list?.items.map((it) => (
        <Card key={it.id}>
          <p className={s.step}>{it.hidden ? "🙈 " : ""}{it.text}</p>
          <p className={s.small}>Ответ: <b>{it.answer}</b>{it.answered ? ` · взяли ${it.taken}/${it.answered}` : ""}</p>
          <div className={s.row} style={{ marginTop: 8 }}>
            <Button variant="ghost" onClick={() => run(() => api.adminHide(it.id, !it.hidden), it.hidden ? "Вопрос снова в игре" : "Вопрос скрыт")}>{it.hidden ? "Вернуть" : "Скрыть"}</Button>
            <Button variant="ghost" onClick={() => { if (confirm("Удалить вопрос насовсем?")) void run(() => api.adminDelete(it.id), "Удалено"); }}>Удалить</Button>
          </div>
        </Card>
      ))}

      <Card>
        <h2>Новый вопрос</h2>
        {(["text", "answer", "explanation"] as const).map((k) => (
          <textarea key={k} className={s.textarea} style={{ marginTop: 8, minHeight: k === "answer" ? 48 : 90 }}
            placeholder={{ text: "Текст вопроса", answer: "Ответ", explanation: "Разбор (обязательно: по нему судья и разбор по шагам)" }[k]}
            value={form[k]} onChange={(e) => setForm({ ...form, [k]: e.target.value })} />
        ))}
        <div style={{ marginTop: 8 }}>
          <Button disabled={!form.text.trim() || !form.answer.trim() || !form.explanation.trim()}
            onClick={() => run(async () => { await api.adminAdd(form); setForm({ text: "", answer: "", explanation: "" }); }, "Вопрос добавлен")}>Добавить</Button>
        </div>
      </Card>

      <Card>
        <h2>Пакетная загрузка</h2>
        <div className={s.row} style={{ margin: "8px 0" }}>
          <Button variant={fmt === "json" ? "primary" : "ghost"} onClick={() => setFmt("json")}>JSON</Button>
          <Button variant={fmt === "csv" ? "primary" : "ghost"} onClick={() => setFmt("csv")}>CSV</Button>
        </div>
        <p className={s.small}>{fmt === "json" ? `Пример: ${EXAMPLE}` : "Колонки: text,answer,explanation,accepted,rejected,source,author,tags,difficulty (списки через |)"}</p>
        <textarea className={s.textarea} style={{ marginTop: 8 }} value={content} onChange={(e) => setContent(e.target.value)} placeholder="Вставь сюда данные" />
        <div className={s.row} style={{ marginTop: 8 }}>
          <Button variant="ghost" disabled={!content.trim()} onClick={() => api.adminImport(fmt, content, true).then(setReport).catch((e) => setMsg(e.message))}>Проверить</Button>
          <Button disabled={!content.trim()} onClick={() => api.adminImport(fmt, content, false).then((r) => { setReport(r); void load(); }).catch((e) => setMsg(e.message))}>Загрузить</Button>
        </div>
        {report && (
          <div style={{ marginTop: 10 }}>
            <p className={s.step}>{report.dry_run ? "Проверка: " : "Загружено: "}годных {report.valid}{report.dry_run ? "" : `, добавлено ${report.added}, дублей ${report.duplicates}`}</p>
            {report.errors.map((e) => <p key={e.row} className={s.small}>Строка {e.row}: {e.reason}</p>)}
          </div>
        )}
      </Card>
      <Button onClick={() => go("home")}>В меню</Button>
    </div>
  );
}
