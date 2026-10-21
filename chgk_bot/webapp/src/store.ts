import { create } from "zustand";
import { api, type Me } from "./api";

interface State {
  me: Me | null;
  error: string;
  screen: "home" | "solo" | "team" | "stats" | "season";
  boot(): Promise<void>;
  go(s: State["screen"]): void;
  refresh(): Promise<void>;
}

export const useApp = create<State>((set) => ({
  me: null,
  error: "",
  screen: "home",
  async boot() {
    try {
      await api.login();
      set({ me: await api.me(), error: "" });
    } catch (e) {
      set({ error: (e as Error).message });
    }
  },
  go: (screen) => set({ screen }),
  async refresh() {
    try { set({ me: await api.me() }); } catch { /* не критично */ }
  },
}));
