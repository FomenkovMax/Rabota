import { create } from "zustand";
import { api, type Me } from "./api";

interface State {
  me: Me | null;
  error: string;
  screen: "home" | "solo" | "team" | "stats" | "season" | "admin";
  dir: 1 | -1;          // направление анимации перехода: вглубь или назад
  boot(): Promise<void>;
  go(s: State["screen"]): void;
  refresh(): Promise<void>;
}

export const useApp = create<State>((set) => ({
  me: null,
  error: "",
  screen: "home",
  dir: 1,
  async boot() {
    try {
      await api.login();
      set({ me: await api.me(), error: "" });
    } catch (e) {
      set({ error: (e as Error).message });
    }
  },
  go: (screen) => set({ screen, dir: screen === "home" ? -1 : 1 }),
  async refresh() {
    try { set({ me: await api.me() }); } catch { /* не критично */ }
  },
}));
