"use client";

import { useEffect, useRef, useState } from "react";

import { Bi } from "./ui";

function fmt(totalSeconds: number) {
  const s = Math.max(0, Math.floor(totalSeconds));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  return h > 0 ? `${h}:${String(m).padStart(2, "0")}:${String(sec).padStart(2, "0")}` : `${m}:${String(sec).padStart(2, "0")}`;
}

/** Time left before auto-delete. `secondsRemaining` comes from the server (avoids clock skew). */
export default function Countdown({ secondsRemaining, onExpire }: { secondsRemaining: number; onExpire?: () => void }) {
  const [left, setLeft] = useState(secondsRemaining);
  const onExpireRef = useRef(onExpire);

  useEffect(() => {
    onExpireRef.current = onExpire;
  }, [onExpire]);

  useEffect(() => {
    const deadline = Date.now() + secondsRemaining * 1000;
    let fired = false;
    const tick = () => {
      const l = (deadline - Date.now()) / 1000;
      setLeft(l);
      if (l <= 0 && !fired) {
        fired = true;
        onExpireRef.current?.();
      }
    };
    const t = setInterval(tick, 1000);
    return () => clearInterval(t);
  }, [secondsRemaining]);

  const urgent = left < 15 * 60;
  return (
    <span className={`inline-flex items-center gap-1.5 text-sm ${urgent ? "text-rose-700" : "text-slate-600"}`}>
      <span aria-hidden>⏳</span>
      <Bi en="Files deleted in" hi="फ़ाइलें हटेंगी" />
      <span className="font-mono font-medium tabular-nums">{fmt(left)}</span>
    </span>
  );
}
