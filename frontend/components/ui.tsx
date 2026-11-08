"use client";

// Small shared UI pieces: bilingual text, buttons, error box, progress bar, status badge.

import Link from "next/link";
import type { ComponentProps, ReactNode } from "react";

import { ApiError } from "@/lib/api";
import { statusColor, statusLabel, type BiText } from "@/lib/labels";
import type { ChapterStatus } from "@/lib/types";

/** "English / हिंदी" — both languages, Hindi slightly smaller. */
export function Bi({ en, hi, className = "" }: BiText & { className?: string }) {
  return (
    <span className={className}>
      {en}
      <span className="opacity-80"> / </span>
      <span lang="hi" className="font-hindi">
        {hi}
      </span>
    </span>
  );
}

/** English over Hindi, for compact buttons on small screens; inline "en / hi" from sm up. */
export function BiStack({ en, hi }: BiText) {
  return (
    <span className="flex flex-col items-center leading-tight sm:flex-row sm:gap-1">
      <span>{en}</span>
      <span className="hidden sm:inline opacity-80">/</span>
      <span lang="hi" className="font-hindi text-[11px] sm:text-sm">
        {hi}
      </span>
    </span>
  );
}

type Variant ="primary" | "secondary" | "danger" | "ghost";

const variants: Record<Variant, string> = {
  primary: "bg-indigo-700 text-white hover:bg-indigo-800 disabled:bg-indigo-300",
  secondary: "bg-white text-slate-800 ring-1 ring-slate-300 hover:bg-slate-50 disabled:text-slate-400",
  danger: "bg-white text-rose-700 ring-1 ring-rose-300 hover:bg-rose-50 disabled:text-rose-300",
  ghost: "text-indigo-700 hover:bg-indigo-50 disabled:text-slate-400",
};

const base =
  "inline-flex items-center justify-center gap-2 rounded-lg px-4 py-2.5 text-sm font-medium transition " +
  "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-600 disabled:cursor-not-allowed min-h-11";

export function Button({ variant = "primary", className = "", ...props }: ComponentProps<"button"> & { variant?: Variant }) {
  return <button type="button" className={`${base} ${variants[variant]} ${className}`} {...props} />;
}

export function ButtonLink({ variant = "secondary", className = "", ...props }: ComponentProps<typeof Link> & { variant?: Variant }) {
  return <Link className={`${base} ${variants[variant]} ${className}`} {...props} />;
}

export function ErrorBox({ error, onDismiss }: { error: unknown; onDismiss?: () => void }) {
  if (!error) return null;
  const e =
    error instanceof ApiError
      ? error
      : new ApiError(0, "error", "Something went wrong. Please try again.", "कुछ गड़बड़ हो गई। कृपया फिर से कोशिश करें।");
  return (
    <div role="alert" className="rounded-lg border border-rose-200 bg-rose-50 p-4 text-sm text-rose-900">
      <div className="flex items-start gap-3">
        <span aria-hidden className="mt-0.5 text-base">⚠</span>
        <div className="flex-1 space-y-1">
          <p>{e.message}</p>
          {e.messageHi && (
            <p lang="hi" className="font-hindi">
              {e.messageHi}
            </p>
          )}
        </div>
        {onDismiss && (
          <button type="button" onClick={onDismiss} className="text-rose-700 hover:text-rose-900" aria-label="Dismiss">
            ✕
          </button>
        )}
      </div>
    </div>
  );
}

export function Notice({ children, tone = "info" }: { children: ReactNode; tone?: "info" | "warn" | "success" }) {
  const tones = {
    info: "border-sky-200 bg-sky-50 text-sky-900",
    warn: "border-amber-200 bg-amber-50 text-amber-900",
    success: "border-emerald-200 bg-emerald-50 text-emerald-900",
  };
  return <div className={`rounded-lg border p-3 text-sm ${tones[tone]}`}>{children}</div>;
}

export function ProgressBar({ value, label }: { value: number; label?: ReactNode }) {
  const pct = Math.max(0, Math.min(100, Math.round(value)));
  return (
    <div className="space-y-1.5">
      {label && (
        <div className="flex justify-between text-sm text-slate-700">
          <span>{label}</span>
          <span className="tabular-nums">{pct}%</span>
        </div>
      )}
      <div
        className="h-2.5 w-full overflow-hidden rounded-full bg-slate-200"
        role="progressbar"
        aria-valuenow={pct}
        aria-valuemin={0}
        aria-valuemax={100}
      >
        <div className="h-full rounded-full bg-indigo-600 transition-[width] duration-500" style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

export function StatusBadge({ status }: { status: ChapterStatus }) {
  const l = statusLabel[status];
  return (
    <span className={`inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-medium ring-1 ${statusColor[status]}`}>
      {status === "translating" && <span className="size-1.5 animate-pulse rounded-full bg-sky-600" aria-hidden />}
      <Bi {...l} />
    </span>
  );
}

export function Spinner({ className = "size-4" }: { className?: string }) {
  return (
    <span
      aria-hidden
      className={`inline-block animate-spin rounded-full border-2 border-current border-r-transparent ${className}`}
    />
  );
}
