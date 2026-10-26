import { animate } from "framer-motion";
import { useEffect, useRef, useState } from "react";

/** Число «набегает» от прежнего значения к новому (на первом показе — от нуля). */
export function CountUp({ value, decimals = 0, suffix = "", duration = 0.9 }: { value: number; decimals?: number; suffix?: string; duration?: number }) {
  const [shown, setShown] = useState(0);
  const prev = useRef(0);
  useEffect(() => {
    const ctl = animate(prev.current, value, { duration, ease: "easeOut", onUpdate: setShown });
    prev.current = value;
    return () => ctl.stop();
  }, [value, duration]);
  return <>{shown.toFixed(decimals).replace(/\.0+$/, "")}{suffix}</>;
}
