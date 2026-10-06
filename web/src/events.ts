import { cents, usd } from "./format";

// Plain-language lines for event records (aios/core/events.py). Unknown types fall back to the type name.

type Payload = Record<string, unknown> | null | undefined;

function s(v: unknown): string {
  return v === null || v === undefined ? "" : String(v);
}

export function eventText(type: string, payload: Payload): string {
  const p = payload ?? {};
  switch (type) {
    case "WORKFLOW_STARTED":
      return `Started ${s(p.command)} run`;
    case "WORKFLOW_FINISHED":
      return `${cap(s(p.command))} run finished: ${s(p.status).toLowerCase().replace(/_/g, " ")}${typeof p.cost_usd === "number" ? ` (${usd(p.cost_usd)})` : ""}`;
    case "DECISION_CREATED":
      return `Decision recorded${p.verdict ? `: ${s(p.verdict).replace(/_/g, " ").toLowerCase()}` : ""}`;
    case "DECISION_APPROVED":
      return "Decision approved";
    case "DECISION_REJECTED":
      return "Decision rejected";
    case "APPROVAL_REQUESTED":
      return `Approval requested: ${s(p.action)}`;
    case "TASK_CREATED":
      return "Task created";
    case "TASK_COMPLETED":
      return "Task completed";
    case "PROJECT_CREATED":
      return `Project created${p.status ? ` (${s(p.status).toLowerCase()})` : ""}`;
    case "PROJECT_BLOCKED":
      return "A project task is blocked";
    case "RESEARCH_COMPLETED":
      return `Research report saved${p.live ? " with live search" : " without live search"}`;
    case "FINANCE_IMPORTED":
      return `Imported ${s(p.accepted)} transactions`;
    case "REVENUE_ADDED":
      return `Revenue added: ${typeof p.cents === "number" ? cents(p.cents) : ""}`;
    case "EXPENSE_ADDED":
      return `Expenses added: ${typeof p.cents === "number" ? cents(p.cents) : ""}`;
    case "AGENT_FAILED":
      return `Agent failed${p.error ? `: ${s(p.error).slice(0, 140)}` : ""}`;
    case "AUDIT_COMPLETED":
      return `Audit completed${p.verdict ? `: ${s(p.verdict).replace(/_/g, " ").toLowerCase()}` : ""}`;
    case "IMPROVEMENT_PROPOSED":
      return "Improvement proposed";
    case "BUDGET_STOP":
      return "Run stopped at its budget limit";
    case "MEMORY_PROMOTED":
      return "A preference was confirmed by your decisions";
    default: {
      const t = type.replace(/_/g, " ").toLowerCase();
      return t.charAt(0).toUpperCase() + t.slice(1);
    }
  }
}

export function eventTone(type: string, payload: Payload): string {
  if (type === "AGENT_FAILED" || type === "BUDGET_STOP" || type === "PROJECT_BLOCKED" || type === "DECISION_REJECTED") return "red";
  if (type === "APPROVAL_REQUESTED") return "amber";
  if (type === "WORKFLOW_FINISHED") {
    const st = s(payload?.status);
    if (st === "FAILED") return "red";
    if (st === "PARTIAL") return "orange";
    if (st === "AWAITING_APPROVAL") return "amber";
    return "green";
  }
  if (type.endsWith("COMPLETED") || type === "DECISION_APPROVED" || type === "REVENUE_ADDED") return "green";
  return "gray";
}

export function actorLabel(actor: string): string {
  if (actor === "founder") return "You";
  if (actor.startsWith("agent:")) return actor.slice(6).toUpperCase().length <= 3 ? actor.slice(6).toUpperCase() : cap(actor.slice(6));
  return cap(actor);
}

function cap(x: string): string {
  return x.charAt(0).toUpperCase() + x.slice(1);
}
