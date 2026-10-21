import { motion } from "framer-motion";
import type { ReactNode } from "react";
import { tg } from "../tg";
import s from "./Button.module.css";

interface Props {
  children: ReactNode;
  onClick?: () => void;
  variant?: "primary" | "ghost";
  disabled?: boolean;
}

export function Button({ children, onClick, variant = "primary", disabled }: Props) {
  return (
    <motion.button
      className={`${s.btn} ${s[variant]}`}
      whileTap={disabled ? undefined : { scale: 0.96 }}
      disabled={disabled}
      onClick={() => {
        tg.haptic("light");
        onClick?.();
      }}
    >
      {children}
    </motion.button>
  );
}
