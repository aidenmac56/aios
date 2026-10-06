import { useMemo, useState } from "react";
import { api } from "../api";
import { Badge, sentence } from "../components/Badge";
import { Callout, Card, PageHead } from "../components/Card";
import { EmptyState, ErrorBox, Gate } from "../components/EmptyState";
import { dateOnly, humanize } from "../format";
import { useAction, useApi } from "../hooks";
import type { Memory, MemoryList } from "../types";

const CATEGORIES = ["FOUNDER", "COMPANY", "PROJECT", "RESEARCH", "DECISION", "FINANCIAL", "AGENT", "SYSTEM"];

export function MemoryPage() {
  const [showSuperseded, setShowSuperseded] = useState(false);
  const { data, error, reload } = useApi<MemoryList>(`/api/memory${showSuperseded ? "?include_superseded=true" : ""}`);

  return (
    <>
      <PageHead
        title="Memory"
        sub="What the company knows about you and itself, with where each item came from."
        actions={
          <label className="check">
            <input type="checkbox" checked={showSuperseded} onChange={(e) => setShowSuperseded(e.target.checked)} />
            Show superseded
          </label>
        }
      />
      <div className="stack">
        <div className="row small" style={{ gap: 14 }}>
          <span className="row" style={{ gap: 6 }}>
            <Badge value="EXPLICIT" kind="memory" /> you said it
          </span>
          <span className="row" style={{ gap: 6 }}>
            <Badge value="CONFIRMED" kind="memory" /> your decisions show it
          </span>
          <span className="row" style={{ gap: 6 }}>
            <Badge value="INFERRED" kind="memory" /> an agent believes it
          </span>
          <span className="row" style={{ gap: 6 }}>
            <Badge value="HYPOTHESIS" kind="memory" /> weak evidence
          </span>
        </div>

        <Gate data={data} error={error} retry={reload} what="Loading memory">
          {(d) => <MemoryBody d={d} reload={reload} />}
        </Gate>

        <AddMemory onAdded={reload} />
      </div>
    </>
  );
}

function MemoryBody({ d, reload }: { d: MemoryList; reload: () => void }) {
  const groups = useMemo(() => {
    const m = new Map<string, Memory[]>();
    for (const x of d.memories) m.set(x.category, [...(m.get(x.category) ?? []), x]);
    return [...m.entries()].sort((a, b) => CATEGORIES.indexOf(a[0]) - CATEGORIES.indexOf(b[0]));
  }, [d.memories]);

  return (
    <>
      {d.conflicts.length > 0 && (
        <Card title="Conflicts" sub="Active memories with the same subject that say different things. Correct one to resolve it.">
          <div className="stack-sm">
            {d.conflicts.map((c) => (
              <Callout key={c.subject} tone="orange" title={humanize(c.subject)}>
                <ul className="bullets">
                  {c.memories.map((m) => (
                    <li key={m.id}>
                      <Badge value={m.status} kind="memory" /> {m.content}
                    </li>
                  ))}
                </ul>
              </Callout>
            ))}
          </div>
        </Card>
      )}
      {groups.length === 0 ? (
        <EmptyState title="No memories yet">Add what matters to you below, or load the reviewed founder seed with <code>aios seed</code>.</EmptyState>
      ) : (
        groups.map(([cat, items]) => (
          <Card key={cat} title={sentence(cat)} sub={`${items.length} item${items.length === 1 ? "" : "s"}`} flush>
            {items.map((m) => (
              <MemoryItem key={m.id} m={m} onChanged={reload} />
            ))}
          </Card>
        ))
      )}
    </>
  );
}

function MemoryItem({ m, onChanged }: { m: Memory; onChanged: () => void }) {
  const [editing, setEditing] = useState(false);
  const [content, setContent] = useState(m.content);
  const [reason, setReason] = useState("");
  const { busy, error, run } = useAction();
  const superseded = m.status === "SUPERSEDED";

  async function save(e: React.FormEvent) {
    e.preventDefault();
    const r = await run(() => api.post<Memory>(`/api/memory/${encodeURIComponent(m.id)}/correct`, { content: content.trim(), reason: reason.trim() || "founder correction" }));
    if (r) {
      setEditing(false);
      onChanged();
    }
  }

  return (
    <div className="mem-item">
      <div className="row-between" style={{ alignItems: "flex-start" }}>
        <span className="row-title">{humanize(m.subject)}</span>
        <Badge value={m.status} kind="memory" />
      </div>
      <p className={superseded ? "mt-8 strike" : "mt-8"}>{m.content}</p>
      <div className="row-meta">
        <span>{sentence(m.provenance)}</span>
        {m.source_ref && <span>Source: {m.source_ref}</span>}
        {m.created_by && <span>By {m.created_by}</span>}
        {m.created_at && <span>{dateOnly(m.created_at.slice(0, 10))}</span>}
        {m.tags && m.tags.length > 0 && <span>Tags: {m.tags.join(", ")}</span>}
        {superseded && m.superseded_by_id && <span>Replaced by a correction</span>}
      </div>
      {!superseded && !editing && (
        <button className="link-btn small mt-8" onClick={() => setEditing(true)}>
          Correct
        </button>
      )}
      {editing && (
        <form className="inline-form" onSubmit={save}>
          <div className="field">
            <label htmlFor={`c-${m.id}`}>Corrected text</label>
            <textarea id={`c-${m.id}`} className="textarea" value={content} onChange={(e) => setContent(e.target.value)} maxLength={4000} />
          </div>
          <div className="field">
            <label htmlFor={`r-${m.id}`}>Reason</label>
            <input id={`r-${m.id}`} className="input" value={reason} onChange={(e) => setReason(e.target.value)} placeholder="founder correction" />
          </div>
          <p className="field-help">The old version is kept as superseded; your correction is recorded as explicit.</p>
          <div className="row">
            <button className="btn btn-primary" type="submit" disabled={busy || !content.trim()}>
              Save correction
            </button>
            <button className="btn btn-ghost" type="button" onClick={() => setEditing(false)}>
              Cancel
            </button>
          </div>
          <ErrorBox error={error} />
        </form>
      )}
    </div>
  );
}

function AddMemory({ onAdded }: { onAdded: () => void }) {
  const [category, setCategory] = useState("FOUNDER");
  const [subject, setSubject] = useState("");
  const [content, setContent] = useState("");
  const [tags, setTags] = useState("");
  const [added, setAdded] = useState<string | null>(null);
  const { busy, error, run } = useAction();

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setAdded(null);
    const r = await run(() =>
      api.post<Memory>("/api/memory", {
        category,
        subject: subject.trim(),
        content: content.trim(),
        tags: tags
          .split(",")
          .map((t) => t.trim())
          .filter(Boolean),
      }),
    );
    if (r) {
      setAdded(r.subject);
      setSubject("");
      setContent("");
      setTags("");
      onAdded();
    }
  }

  return (
    <Card title="Add a memory" sub="What you add here is recorded as EXPLICIT: you said it, so agents treat it as fact.">
      <form className="form" onSubmit={submit}>
        <div className="form-grid">
          <div className="field">
            <label htmlFor="m-cat">Category</label>
            <select id="m-cat" className="select" value={category} onChange={(e) => setCategory(e.target.value)}>
              {CATEGORIES.map((c) => (
                <option key={c} value={c}>
                  {sentence(c)}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label htmlFor="m-sub">Subject</label>
            <input id="m-sub" className="input" value={subject} onChange={(e) => setSubject(e.target.value)} placeholder="weekly_hours_available" maxLength={200} />
          </div>
          <div className="field">
            <label htmlFor="m-tags">Tags</label>
            <input id="m-tags" className="input" value={tags} onChange={(e) => setTags(e.target.value)} placeholder="priority, principle:preserve_cash" />
          </div>
        </div>
        <div className="field">
          <label htmlFor="m-content">What should the company remember?</label>
          <textarea id="m-content" className="textarea" value={content} onChange={(e) => setContent(e.target.value)} maxLength={4000} placeholder="I can spend about 15 hours a week on the business until summer." />
        </div>
        <div>
          <button className="btn btn-primary" type="submit" disabled={busy || !subject.trim() || !content.trim()}>
            Add memory
          </button>
        </div>
        <ErrorBox error={error} />
        {added && <Callout tone="green">Saved “{humanize(added)}” as explicit.</Callout>}
      </form>
    </Card>
  );
}
