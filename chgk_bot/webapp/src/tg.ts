// Тонкая обёртка над window.Telegram.WebApp: вне Telegram (обычный браузер) всё безопасно не делает ничего.
type Haptic = "light" | "medium" | "heavy" | "success" | "error";

interface TgWebApp {
  initData: string;
  ready(): void;
  expand(): void;
  disableVerticalSwipes?(): void;
  HapticFeedback?: {
    impactOccurred(s: string): void;
    notificationOccurred(s: string): void;
  };
}

const wa = (): TgWebApp | undefined => (window as unknown as { Telegram?: { WebApp?: TgWebApp } }).Telegram?.WebApp;

export const tg = {
  initData: () => wa()?.initData ?? "",
  inTelegram: () => !!wa()?.initData,
  init() {
    const w = wa();
    w?.ready();
    w?.expand();
    w?.disableVerticalSwipes?.();
  },
  haptic(kind: Haptic) {
    const h = wa()?.HapticFeedback;
    if (!h) return;
    if (kind === "success" || kind === "error") h.notificationOccurred(kind);
    else h.impactOccurred(kind);
  },
};
