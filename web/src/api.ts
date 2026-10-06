// Typed fetch helper. Every non-2xx response throws ApiError carrying the API's {code, message}.
// AIOSError responses look like {code, message, ...details}; FastAPI HTTPException looks like
// {detail: "..."}; request validation failures look like {detail: [{loc, msg}]}. All three are normalized.

const TOKEN_KEY = "aios.api_token";

let token: string | null = readStoredToken();
const authListeners = new Set<() => void>();

function readStoredToken(): string | null {
  try {
    return window.localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function getToken(): string | null {
  return token;
}

export function setToken(value: string | null, remember = true): void {
  token = value && value.trim() ? value.trim() : null;
  try {
    if (token && remember) window.localStorage.setItem(TOKEN_KEY, token);
    else window.localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* storage unavailable: keep the token in memory only */
  }
}

/** Called whenever the server answers 401, so the app can show the token prompt. */
export function onAuthRequired(fn: () => void): () => void {
  authListeners.add(fn);
  return () => authListeners.delete(fn);
}

export class ApiError extends Error {
  status: number;
  code: string;
  body: Record<string, unknown> | null;

  constructor(status: number, code: string, message: string, body: Record<string, unknown> | null) {
    super(message);
    this.status = status;
    this.code = code;
    this.body = body;
  }
}

function normalizeError(status: number, body: unknown, fallback: string): ApiError {
  if (body && typeof body === "object") {
    const b = body as Record<string, unknown>;
    if (typeof b.code === "string" && typeof b.message === "string") {
      return new ApiError(status, b.code, b.message, b);
    }
    if (typeof b.detail === "string") {
      return new ApiError(status, status === 401 ? "unauthorized" : `http_${status}`, b.detail, b);
    }
    if (Array.isArray(b.detail)) {
      const msg = b.detail
        .map((d) => {
          const item = d as { loc?: unknown[]; msg?: string };
          const where = Array.isArray(item.loc) ? item.loc.filter((x) => x !== "body").join(".") : "";
          return where ? `${where}: ${item.msg ?? "invalid"}` : item.msg ?? "invalid";
        })
        .join("; ");
      return new ApiError(status, "invalid_request", msg || fallback, b);
    }
  }
  return new ApiError(status, `http_${status}`, fallback, null);
}

type Body = Record<string, unknown> | FormData | undefined;

async function request<T>(method: string, path: string, body?: Body): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json" };
  if (token) headers.Authorization = `Bearer ${token}`;
  let payload: BodyInit | undefined;
  if (body instanceof FormData) {
    payload = body;
  } else if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    payload = JSON.stringify(body);
  }
  let res: Response;
  try {
    res = await fetch(path, { method, headers, body: payload });
  } catch {
    throw new ApiError(0, "network_error", "Cannot reach the API. Is `aios serve` running?", null);
  }
  const text = await res.text();
  let parsed: unknown = null;
  if (text) {
    try {
      parsed = JSON.parse(text);
    } catch {
      parsed = null;
    }
  }
  if (!res.ok) {
    if (res.status === 401) authListeners.forEach((fn) => fn());
    throw normalizeError(res.status, parsed, `${method} ${path} failed with HTTP ${res.status}`);
  }
  return parsed as T;
}

export const api = {
  get: <T>(path: string) => request<T>("GET", path),
  post: <T>(path: string, body?: Body) => request<T>("POST", path, body ?? {}),
  put: <T>(path: string, body?: Body) => request<T>("PUT", path, body ?? {}),
  patch: <T>(path: string, body?: Body) => request<T>("PATCH", path, body ?? {}),
};

export function errorMessage(e: unknown): string {
  if (e instanceof ApiError) {
    if (e.code === "missing_credentials" && !/\.env/.test(e.message)) {
      return `${e.message} Add ANTHROPIC_API_KEY to .env and restart the server.`;
    }
    return e.message;
  }
  if (e instanceof Error) return e.message;
  return String(e);
}
