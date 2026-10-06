import type { ReactNode } from "react";

export type Tone = "green" | "blue" | "amber" | "orange" | "red" | "gray" | "accent";
export type BadgeKind = "status" | "verdict" | "confidence" | "memory" | "severity" | "approval";

// One color language for every status in the system:
// green = done/passed, blue = in motion, amber = waiting on the founder or conditional,
// orange = partial / needs review, red = failed or blocked, gray = inert.
const STATUS: Record<string, Tone> = {
  COMPLETED: "green",
  PASS: "green",
  APPROVED: "green",
  IMPLEMENTED: "green",
  VERIFIED: "green",
  ACTIVE: "green",
  GOOD: "green",
  ACTUAL: "green",
  TESTED: "green",

  RUNNING: "blue",
  PENDING: "blue",
  READY: "blue",
  TESTING: "blue",

  AWAITING_APPROVAL: "amber",
  PASS_WITH_CONDITIONS: "amber",
  PENDING_APPROVAL: "amber",
  APPROVAL_REQUIRED: "amber",
  WAITING: "amber",
  MIXED: "amber",
  COMMITTED: "amber",

  PARTIAL: "orange",
  REVIEW_REQUIRED: "orange",
  ROLLED_BACK: "orange",
  PAUSED: "orange",

  FAILED: "red",
  BLOCK: "red",
  BLOCKED: "red",
  REJECTED: "red",
  POOR: "red",

  PLANNED: "gray",
  PROPOSED: "gray",
  CANCELLED: "gray",
  SUPERSEDED: "gray",
  EXPIRED: "gray",
};

const VERDICT: Record<string, Tone> = {
  BUILD: "green",
  PROCEED: "green",
  INVESTIGATE: "blue",
  WATCH: "amber",
  PASS: "gray",
  DO_NOT_PROCEED: "red",
  NO_DECISION: "gray",
  // risk-audit verdicts can also arrive through the verdict kind
  PASS_WITH_CONDITIONS: "amber",
  REVIEW_REQUIRED: "orange",
  BLOCK: "red",
};

const CONFIDENCE: Record<string, Tone> = { HIGH: "green", MEDIUM: "blue", LOW: "amber" };
const MEMORY: Record<string, Tone> = { EXPLICIT: "green", CONFIRMED: "blue", INFERRED: "amber", HYPOTHESIS: "gray", SUPERSEDED: "gray" };
const SEVERITY: Record<string, Tone> = { CRITICAL: "red", MAJOR: "orange", MINOR: "gray", HIGH: "red", MEDIUM: "amber", LOW: "gray" };

export function toneFor(value: string | null | undefined, kind: BadgeKind = "status"): Tone {
  if (!value) return "gray";
  const v = value.toUpperCase();
  switch (kind) {
    case "verdict":
      return VERDICT[v] ?? STATUS[v] ?? "gray";
    case "confidence":
      return CONFIDENCE[v] ?? "gray";
    case "memory":
      return MEMORY[v] ?? "gray";
    case "severity":
      return SEVERITY[v] ?? "gray";
    case "approval":
      return v === "PENDING" ? "amber" : STATUS[v] ?? "gray";
    default:
      return STATUS[v] ?? "gray";
  }
}

export function sentence(value: string): string {
  const s = value.replace(/_/g, " ").toLowerCase();
  return s.charAt(0).toUpperCase() + s.slice(1);
}

const LIVE = new Set(["RUNNING", "PENDING"]);

export function Badge({
  value,
  kind = "status",
  label,
  tone,
  size,
  title,
  children,
}: {
  value?: string | null;
  kind?: BadgeKind;
  label?: ReactNode;
  tone?: Tone;
  size?: "lg";
  title?: string;
  children?: ReactNode;
}) {
  const t = tone ?? toneFor(value, kind);
  const live = kind === "status" && !!value && LIVE.has(value.toUpperCase());
  const text = children ?? label ?? (value ? sentence(value) : "Unknown");
  const cls = ["badge", `tone-${t}`, live ? "live" : "", size === "lg" ? "lg" : ""].filter(Boolean).join(" ");
  return (
    <span className={cls} title={title ?? value ?? undefined}>
      {text}
    </span>
  );
}
