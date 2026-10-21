import { tg } from "./tg";

let token = "";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function call<T>(path: string, body?: unknown): Promise<T> {
  const r = await fetch(path, {
    method: body === undefined ? "GET" : "POST",
    headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new ApiError(r.status, data.detail || "Ошибка сервера");
  return data as T;
}

export interface Stats { played: number; points: number; correct: number; close: number }
export interface Me {
  user: { id: number; name: string };
  stats: Stats;
  brand: { game_name: string };
  think_seconds: number;
}
export interface Question { id: string; text: string; media: { type: string; url: string }[]; author: string }
export interface Round {
  round_id: string; question: Question; fresh_left: number; think_seconds: number;
  server_now_ms: number; deadline_ms: number;
}
export interface Reveal {
  answer: string; accepted: string[]; accept_note: string; explanation: string;
  author: string; source: string; url: string;
}
export interface Verdict { level: "correct" | "close" | "wrong"; score: number; comment: string; source: string; disputed: boolean }
export interface AnswerResult { timeout: boolean; verdict: Verdict; reveal: Reveal; stats?: Stats }
export interface Steps { steps: { clue: string; inference: string; how: string }[]; lesson: string }

export const api = {
  async login() {
    const res = tg.inTelegram()
      ? await call<{ token: string }>("/api/auth/telegram", { init_data: tg.initData() })
      : await call<{ token: string }>("/api/auth/dev", { id: Number(new URLSearchParams(location.search).get("dev") || 1), name: "Dev" + (new URLSearchParams(location.search).get("dev") || 1) }); // работает только при DEV_AUTH=1 на сервере
    token = res.token;
  },
  me: () => call<Me>("/api/me"),
  next: () => call<Round>("/api/solo/next", {}),
  answer: (round_id: string, answer: string) => call<AnswerResult>("/api/solo/answer", { round_id, answer }),
  skip: (round_id: string) => call<{ reveal: Reveal; stats: Stats }>("/api/solo/skip", { round_id }),
  steps: (qid: string) => call<{ steps: Steps | null }>(`/api/questions/${qid}/steps`, {}),
};

// ---------- командная игра ----------
export interface Verdict2 extends Verdict { overridden?: boolean }
export interface GameView {
  mode: "sport" | "wheel"; status: string; phase: "idle" | "think" | "answer" | "judging" | "review" | "finished";
  captain_id: number; deadline_ms: number; idx: number; total: number; tour: [number, number] | null;
  score: number; experts: number; viewers: number; played: number[];
  spin: { sector: number; turns: number; duration_ms: number; offset: number; n: number } | null;
  answer: string | null; verdict: Verdict2 | null; think: number;
  question: { id: string; text: string; media: unknown[] } | null;
  reveal: Reveal | null;
  log: { qid: string; answer: string | null; level: string; score: number }[] | null;
}
export interface RoomState {
  server_now_ms: number; notice: string; players: { id: number; name: string }[]; game: GameView | null;
}

export function openRoom(onState: (s: RoomState) => void, onError: (m: string) => void) {
  let ws: WebSocket | null = null;
  let closed = false;
  const connect = () => {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    ws = new WebSocket(`${proto}://${location.host}/api/ws?token=${encodeURIComponent(token)}`);
    ws.onmessage = (e) => {
      const m = JSON.parse(e.data);
      if (m.type === "state") onState(m);
      else if (m.type === "error") onError(m.message);
    };
    ws.onclose = () => { if (!closed) setTimeout(connect, 1500); };   // переподключение; сервер пришлёт актуальное состояние
  };
  connect();
  return {
    send: (msg: Record<string, unknown>) => ws?.readyState === 1 && ws.send(JSON.stringify(msg)),
    close: () => { closed = true; ws?.close(); },
  };
}
