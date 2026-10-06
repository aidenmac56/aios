import { useEffect, useState } from "react";

// Hash router: #/executive, #/runs/<id>, #/agents/<id>, #/projects/<id>, #/research/<id>.

export interface Route {
  page: string;
  id: string | null;
  query: URLSearchParams;
}

export function parseHash(hash: string): Route {
  const raw = hash.replace(/^#\/?/, "");
  const [path, qs] = raw.split("?");
  const parts = (path || "").split("/").filter(Boolean).map(decodeURIComponent);
  return { page: parts[0] || "executive", id: parts[1] ?? null, query: new URLSearchParams(qs || "") };
}

export function useRoute(): Route {
  const [route, setRoute] = useState<Route>(() => parseHash(window.location.hash));
  useEffect(() => {
    const onChange = () => setRoute(parseHash(window.location.hash));
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);
  return route;
}

export function href(page: string, id?: string | null): string {
  return id ? `#/${page}/${encodeURIComponent(id)}` : `#/${page}`;
}

export function navigate(page: string, id?: string | null): void {
  window.location.hash = href(page, id);
}
