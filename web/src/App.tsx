import { useCallback, useEffect, useState, type ReactNode } from "react";
import { api, ApiError, getToken, onAuthRequired, setToken } from "./api";
import { CommandBar } from "./components/CommandBar";
import { ErrorBox } from "./components/EmptyState";
import { href, useRoute } from "./router";
import type { Approval, Health } from "./types";
import { ExecutivePage } from "./pages/Executive";
import { RunDetailPage } from "./pages/RunDetail";
import { RunsPage } from "./pages/Runs";
import { CompanyPage } from "./pages/Company";
import { AgentsPage } from "./pages/Agents";
import { FinancePage } from "./pages/Finance";
import { ProjectsPage } from "./pages/Projects";
import { ResearchPage } from "./pages/Research";
import { DecisionsPage } from "./pages/Decisions";
import { AuditsPage } from "./pages/Audits";
import { MemoryPage } from "./pages/Memory";
import { CostsPage } from "./pages/Costs";
import { SettingsPage } from "./pages/Settings";

type Auth = "checking" | "ok" | "need_token" | "offline";
type Theme = "auto" | "dark" | "light";

const NAV: { label: string; items: { page: string; label: string }[] }[] = [
  {
    label: "Command",
    items: [
      { page: "executive", label: "Executive" },
      { page: "decisions", label: "Decisions" },
      { page: "runs", label: "Runs" },
    ],
  },
  {
    label: "Company",
    items: [
      { page: "company", label: "Company" },
      { page: "projects", label: "Projects" },
      { page: "agents", label: "Agents" },
      { page: "research", label: "Research" },
      { page: "memory", label: "Memory" },
    ],
  },
  {
    label: "Money",
    items: [
      { page: "finance", label: "Finance" },
      { page: "costs", label: "AI costs" },
    ],
  },
  {
    label: "System",
    items: [
      { page: "audits", label: "Audits" },
      { page: "settings", label: "Settings" },
    ],
  },
];

const THEME_KEY = "aios.theme";

function readTheme(): Theme {
  try {
    const t = window.localStorage.getItem(THEME_KEY);
    return t === "dark" || t === "light" ? t : "auto";
  } catch {
    return "auto";
  }
}

function applyTheme(t: Theme) {
  const root = document.documentElement;
  if (t === "auto") root.removeAttribute("data-theme");
  else root.setAttribute("data-theme", t);
  try {
    if (t === "auto") window.localStorage.removeItem(THEME_KEY);
    else window.localStorage.setItem(THEME_KEY, t);
  } catch {
    /* ignore */
  }
}

export function App() {
  const route = useRoute();
  const [auth, setAuth] = useState<Auth>("checking");
  const [health, setHealth] = useState<Health | null>(null);
  const [epoch, setEpoch] = useState(0);
  const [pending, setPending] = useState<number | null>(null);
  const [menuOpen, setMenuOpen] = useState(false);
  const [theme, setTheme] = useState<Theme>(readTheme);

  useEffect(() => applyTheme(theme), [theme]);

  const check = useCallback(async () => {
    setAuth("checking");
    try {
      setHealth(await api.get<Health>("/api/health"));
    } catch {
      setAuth("offline");
      return;
    }
    try {
      await api.get("/api/settings");
      setAuth("ok");
    } catch (e) {
      setAuth(e instanceof ApiError && e.status === 401 ? "need_token" : "ok");
    }
  }, []);

  useEffect(() => {
    void check();
  }, [check]);

  useEffect(() => onAuthRequired(() => setAuth("need_token")), []);

  // Pending approvals count for the nav; refreshed on navigation and every 20 s.
  useEffect(() => {
    if (auth !== "ok") return;
    let alive = true;
    const load = () =>
      api
        .get<Approval[]>("/api/approvals?status=PENDING")
        .then((a) => alive && setPending(a.length))
        .catch(() => undefined);
    load();
    const t = window.setInterval(load, 20000);
    return () => {
      alive = false;
      window.clearInterval(t);
    };
  }, [auth, route.page, route.id, epoch]);

  useEffect(() => {
    setMenuOpen(false);
    window.scrollTo(0, 0);
  }, [route.page, route.id]);

  if (auth === "offline") {
    return (
      <div className="fullpage-note">
        <h1 className="page-title">The API is not answering</h1>
        <p className="ink-2">
          Start the server with <code>aios serve</code> (it listens on 127.0.0.1:8787), then try again. In development, <code>npm run dev</code> proxies <code>/api</code> to that address.
        </p>
        <div>
          <button className="btn btn-primary" onClick={() => void check()}>
            Try again
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="shell">
      <aside className={menuOpen ? "sidebar open" : "sidebar"}>
        <div className="sidebar-top">
          <a className="brand" href={href("executive")}>
            <span className="brand-mark" aria-hidden="true">
              AI
            </span>
            <span>
              <div className="brand-name">AI Company OS</div>
              <div className="brand-sub">Command center</div>
            </span>
          </a>
          <button className="btn btn-sm menu-toggle" aria-expanded={menuOpen} onClick={() => setMenuOpen((o) => !o)}>
            {menuOpen ? "Close" : "Menu"}
          </button>
        </div>
        <nav className="nav" aria-label="Sections">
          {NAV.map((g) => (
            <div key={g.label}>
              <div className="nav-group-label">{g.label}</div>
              {g.items.map((it) => (
                <a key={it.page} className="nav-link" href={href(it.page)} aria-current={route.page === it.page ? "page" : undefined}>
                  <span>{it.label}</span>
                  {it.page === "decisions" && pending ? (
                    <span className="nav-count" aria-label={`${pending} pending`}>
                      {pending}
                    </span>
                  ) : null}
                </a>
              ))}
            </div>
          ))}
        </nav>
        <div className="sidebar-foot">
          {health && (
            <>
              <div className="server-line">
                <span className={health.llm_credentials ? "dot ok" : "dot warn"} />
                {health.llm_credentials ? "Model key present" : "No model key"}
              </div>
              <div className="server-line">
                <span className={health.web_search ? "dot ok" : "dot"} />
                {health.web_search ? "Web search on" : "Web search off"}
              </div>
            </>
          )}
          <div className="segmented" role="group" aria-label="Theme">
            {(["auto", "dark", "light"] as Theme[]).map((t) => (
              <button key={t} aria-pressed={theme === t} onClick={() => setTheme(t)}>
                {t === "auto" ? "Auto" : t === "dark" ? "Dark" : "Light"}
              </button>
            ))}
          </div>
        </div>
      </aside>

      <div className="main">
        <CommandBar health={health} />
        <main className="content" key={`${route.page}/${route.id ?? ""}/${epoch}`}>
          {auth === "checking" ? <div className="loading">Connecting…</div> : <Page page={route.page} id={route.id} />}
        </main>
      </div>

      {auth === "need_token" && (
        <TokenPrompt
          onAccepted={() => {
            setAuth("ok");
            setEpoch((n) => n + 1);
          }}
        />
      )}
    </div>
  );
}

function Page({ page, id }: { page: string; id: string | null }): ReactNode {
  switch (page) {
    case "executive":
      return <ExecutivePage />;
    case "runs":
      return id ? <RunDetailPage id={id} /> : <RunsPage />;
    case "company":
      return <CompanyPage />;
    case "agents":
      return <AgentsPage id={id} />;
    case "finance":
      return <FinancePage />;
    case "projects":
      return <ProjectsPage id={id} />;
    case "research":
      return <ResearchPage id={id} />;
    case "decisions":
      return <DecisionsPage />;
    case "audits":
      return <AuditsPage />;
    case "memory":
      return <MemoryPage />;
    case "costs":
      return <CostsPage />;
    case "settings":
      return <SettingsPage />;
    default:
      return (
        <div className="empty">
          <div className="empty-title">There is no page called “{page}”.</div>
          <a href={href("executive")}>Go to the executive view</a>
        </div>
      );
  }
}

function TokenPrompt({ onAccepted }: { onAccepted: () => void }) {
  const [value, setValue] = useState("");
  const [remember, setRemember] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const hadToken = !!getToken();

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setToken(value, remember);
    try {
      await api.get("/api/settings");
      onAccepted();
    } catch (err) {
      setToken(null);
      setError(err instanceof ApiError && err.status === 401 ? new ApiError(401, "unauthorized", "That token was not accepted. Check AIOS_API_TOKEN in the server's .env.", null) : err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="overlay" role="dialog" aria-modal="true" aria-labelledby="token-title">
      <form className="modal" onSubmit={submit}>
        <h2 id="token-title" className="panel-title" style={{ fontSize: 16 }}>
          {hadToken ? "Your saved token no longer works" : "This server needs an API token"}
        </h2>
        <p className="ink-2 small">
          The server was started with <code>AIOS_API_TOKEN</code>. Paste the same value here. It is sent as a bearer token with every request.
        </p>
        <div className="field">
          <label htmlFor="token-input">API token</label>
          <input id="token-input" className="input" type="password" autoFocus autoComplete="off" value={value} onChange={(e) => setValue(e.target.value)} />
        </div>
        <label className="check">
          <input type="checkbox" checked={remember} onChange={(e) => setRemember(e.target.checked)} />
          Remember on this device
        </label>
        <ErrorBox error={error} />
        <div className="row" style={{ justifyContent: "flex-end" }}>
          <button className="btn btn-primary" type="submit" disabled={busy || !value.trim()}>
            {busy ? "Checking…" : "Connect"}
          </button>
        </div>
      </form>
    </div>
  );
}
