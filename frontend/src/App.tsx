import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, getHealth, sendMessage, type ChatMetadata, type Health } from "./api";
import { AssistantMessage } from "./components/AssistantMessage";
import { Composer } from "./components/Composer";
import { AlertIcon, ChevronIcon, ComposeIcon, SlidersIcon } from "./components/icons";
import { SettingsPanel } from "./components/SettingsPanel";
import { newSessionId } from "./session";

type Entry =
  | { id: number; role: "user"; content: string }
  | { id: number; role: "assistant"; content: string; metadata: ChatMetadata }
  | { id: number; role: "error"; content: string };

// Omit<> over a union collapses it, this keeps each variant intact
type NewEntry = Entry extends infer E ? (E extends Entry ? Omit<E, "id"> : never) : never;

const SUGGESTIONS = [
  "What is the capital of France?",
  "Explain HTTP 429 in one sentence.",
  "Give me three tips for writing clean Python.",
];

function errorText(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 503) return "All model providers are unavailable right now. Every API key failed, so please try again in a moment.";
    if (err.status === 422) return `The request was rejected: ${err.message}`;
    if (err.status === 0) {
      return "Can't reach the server. It may be waking up (the free hosting sleeps when idle), so try again in about 30 seconds.";
    }
    return `Something went wrong (${err.status}): ${err.message}`;
  }
  return "Something went wrong. Please try again.";
}

export default function App() {
  // a fresh session on every page load
  const [sessionId, setSessionId] = useState(newSessionId);
  const [entries, setEntries] = useState<Entry[]>([]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [health, setHealth] = useState<Health | null>(null);
  const [healthError, setHealthError] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [systemPrompt, setSystemPrompt] = useState("");
  const [sentSystemPrompt, setSentSystemPrompt] = useState("");
  const [simulateFailure, setSimulateFailure] = useState("");
  const [scrolled, setScrolled] = useState(false);
  const nextId = useRef(1);
  const scrollRef = useRef<HTMLElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  // Free hosting sleeps when idle and takes up to a minute to wake, so keep
  // checking for a while instead of giving up after the first failed request.
  useEffect(() => {
    let cancelled = false;
    let timer: number | undefined;
    const started = Date.now();

    async function check() {
      try {
        const h = await getHealth();
        if (cancelled) return;
        setHealth(h);
        setHealthError(false);
      } catch {
        if (cancelled) return;
        const waited = Date.now() - started;
        setHealthError(waited > 120_000);
        if (waited <= 120_000) timer = window.setTimeout(check, 4000);
      }
    }

    check();
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, []);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [entries, busy]);

  const closeSettings = useCallback(() => setSettingsOpen(false), []);

  function push(entry: NewEntry) {
    setEntries((prev) => [...prev, { ...entry, id: nextId.current++ } as Entry]);
  }

  async function send(text: string) {
    const message = text.trim();
    if (!message || busy) return;

    setDraft("");
    push({ role: "user", content: message });
    setBusy(true);

    // only send the system prompt when it changed, the server remembers it per session
    const promptChanged = systemPrompt.trim() !== sentSystemPrompt;
    const failure = simulateFailure;
    setSimulateFailure(""); // one request only, like the header itself

    try {
      const res = await sendMessage(sessionId, message, {
        systemPrompt: promptChanged ? systemPrompt.trim() : undefined,
        simulateFailure: failure || undefined,
      });
      if (promptChanged) setSentSystemPrompt(systemPrompt.trim());
      push({ role: "assistant", content: res.reply, metadata: res.metadata });
      if (!health) getHealth().then(setHealth).catch(() => {});
    } catch (err) {
      push({ role: "error", content: errorText(err) });
    } finally {
      setBusy(false);
    }
  }

  function newChat() {
    setSessionId(newSessionId());
    setEntries([]);
    setSentSystemPrompt("");
    setDraft("");
  }

  const status = health
    ? `${health.keys_configured} keys · cache ${health.cache_enabled ? "on" : "off"}`
    : healthError
      ? "Backend unreachable"
      : "Waking up server…";

  return (
    <div className="app">
      <header className={`toolbar top ${scrolled ? "edge" : ""}`}>
        <button className="icon-button" onClick={newChat} disabled={busy} aria-label="New chat" title="New chat">
          <ComposeIcon />
        </button>
        <div className="title">
          <h1>Assistant</h1>
          <p className={`status ${health ? "ok" : healthError ? "down" : "waking"}`} title={sessionId}>
            {status}
          </p>
        </div>
        <button
          className={`icon-button ${settingsOpen ? "active" : ""}`}
          onClick={() => setSettingsOpen((o) => !o)}
          aria-label="Settings"
          aria-expanded={settingsOpen}
          title="Settings"
        >
          <SlidersIcon />
        </button>
      </header>

      <SettingsPanel
        open={settingsOpen}
        onClose={closeSettings}
        systemPrompt={systemPrompt}
        onSystemPromptChange={setSystemPrompt}
        simulateFailure={simulateFailure}
        onSimulateFailureChange={setSimulateFailure}
        simulationAvailable={health?.failure_simulation ?? true}
      />

      <main className="chat" ref={scrollRef} onScroll={(e) => setScrolled(e.currentTarget.scrollTop > 4)}>
        <div className="thread">
          {entries.length === 0 && (
            <div className="empty">
              <h2>Ask anything.</h2>
              <p>
                Each reply shows whether it came from the live model or the cache, which model answered, how long it took
                and the tokens that request used.
              </p>
              <div className="group suggestions">
                {SUGGESTIONS.map((s) => (
                  <button key={s} className="group-row" onClick={() => send(s)} disabled={busy}>
                    <span>{s}</span>
                    <span className="row-chevron">
                      <ChevronIcon />
                    </span>
                  </button>
                ))}
              </div>
            </div>
          )}

          {entries.map((entry) => {
            if (entry.role === "assistant") {
              return <AssistantMessage key={entry.id} content={entry.content} metadata={entry.metadata} />;
            }
            if (entry.role === "error") {
              return (
                <div key={entry.id} className="row row-in" role="alert">
                  <div className="bubble bubble-error">
                    <AlertIcon />
                    <span>{entry.content}</span>
                  </div>
                </div>
              );
            }
            return (
              <div key={entry.id} className="row row-out">
                <div className="bubble bubble-out">{entry.content}</div>
              </div>
            );
          })}

          {busy && (
            <div className="row row-in" aria-live="polite" aria-label="Assistant is typing">
              <div className="bubble bubble-in typing">
                <span />
                <span />
                <span />
              </div>
            </div>
          )}
          <div ref={bottomRef} className="bottom-spacer" />
        </div>
      </main>

      <footer className="toolbar bottom">
        {simulateFailure && (
          <div className="drill-banner">
            Next message simulates <code>{simulateFailure}</code>
            <button className="text-button small" onClick={() => setSimulateFailure("")}>
              Cancel
            </button>
          </div>
        )}
        <Composer value={draft} onChange={setDraft} onSend={() => send(draft)} busy={busy} />
      </footer>
    </div>
  );
}
