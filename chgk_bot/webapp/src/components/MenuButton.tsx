import { useApp } from "../store";
import { tg } from "../tg";
import { Button } from "./Button";

/** «В меню» только вне Telegram: в Telegram назад ведёт системная кнопка в шапке. */
export function MenuButton({ variant = "primary" }: { variant?: "primary" | "ghost" }) {
  const { go } = useApp();
  if (tg.inTelegram()) return null;
  return <Button variant={variant} onClick={() => go("home")}>В меню</Button>;
}
