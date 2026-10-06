import type { ReactNode } from "react";
import { errorMessage, ApiError } from "../api";

export function EmptyState({ title, children, action }: { title: ReactNode; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="empty">
      <div className="empty-title">{title}</div>
      {children && <div>{children}</div>}
      {action}
    </div>
  );
}

export function Loading({ what = "Loading" }: { what?: string }) {
  return (
    <div className="loading" role="status">
      {what}…
    </div>
  );
}

export function ErrorBox({ error, retry }: { error: unknown; retry?: () => void }) {
  if (!error) return null;
  const code = error instanceof ApiError ? error.code : null;
  const local = !(error instanceof ApiError) || error.status === 0;
  const title =
    local && code !== "network_error"
      ? "Check the form"
      : code === "missing_credentials"
      ? "Model credentials missing"
      : code === "network_error"
        ? "API unreachable"
        : code === "unauthorized"
          ? "Not authorized"
          : code === "validation_failed"
            ? "Not allowed"
            : "Request failed";
  return (
    <div className={`callout tone-red`} role="alert">
      <div className="callout-title">{title}</div>
      <div>{errorMessage(error)}</div>
      {retry && (
        <button className="btn btn-sm mt-8" onClick={retry}>
          Try again
        </button>
      )}
    </div>
  );
}

/** Standard wrapper for a page that depends on one GET. */
export function Gate<T>({ data, error, retry, what, children }: { data: T | null; error: unknown; retry?: () => void; what?: string; children: (d: T) => ReactNode }) {
  if (data) return <>{children(data)}</>;
  if (error) return <ErrorBox error={error} retry={retry} />;
  return <Loading what={what} />;
}
