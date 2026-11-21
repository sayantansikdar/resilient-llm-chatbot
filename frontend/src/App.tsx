import { useEffect, useRef, useState } from "react";
import { ApiError, getHealth, sendMessage, type ChatMetadata, type Health } from "./api";
import { AssistantMessage } from "./components/AssistantMessage";
import { Composer } from "./components/Composer";
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
    if (err.status === 503) return "All model providers are unavailable right now (every API key failed). Please try again in a moment.";
    if (err.status === 422) return `The request was rejected: ${err.message}`;
    if (err.status === 0) return err.message;
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
  const [showSettings, setShowSettings] = useState(false);
  const [systemPrompt, setSystemPrompt] = useState("");
  const [sentSystemPrompt, setSentSystemPrompt] = useState("");
  const [simulateFailure, setSimulateFailure] = useState("");
  const nextId = useRef(1);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    getHealth()
      .then(setHealth)
      .catch(() => setHealthError(true));
  }, []);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [entries, busy]);

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

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <span className="logo" aria-hidden>◆</span>
          <div>
            <h1>Resilient Chat</h1>
            <p className="session" title="Session id">{sessionId}</p>
          </div>
        </div>
        <div className="topbar-actions">
          <span className={`status ${health ? "ok" : healthError ? "down" : ""}`}>
            {health
              ? `${health.keys_configured} keys · cache ${health.cache_enabled ? "on" : "off"}`
              : healthError
                ? "backend unreachable"
                : "connecting…"}
          </span>
          <button className="ghost" onClick={() => setShowSettings((s) => !s)} aria-expanded={showSettings}>
            Settings
          </button>
          <button className="ghost" onClick={newChat} disabled={busy}>
            New chat
          </button>
        </div>
      </header>

      {showSettings && (
        <SettingsPanel
          systemPrompt={systemPrompt}
          onSystemPromptChange={setSystemPrompt}
          simulateFailure={simulateFailure}
          onSimulateFailureChange={setSimulateFailure}
          simulationAvailable={health?.failure_simulation ?? true}
        />
      )}

      <main className="chat">
        {entries.length === 0 && (
          <div className="empty">
            <h2>Ask anything</h2>
            <p>
              Every reply shows where it came from (live model or cache), which model answered, how long it took and
              the tokens used by that request.
            </p>
            <div className="suggestions">
              {SUGGESTIONS.map((s) => (
                <button key={s} className="suggestion" onClick={() => send(s)} disabled={busy}>
                  {s}
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
              <div key={entry.id} className="message error" role="alert">
                <div className="bubble">{entry.content}</div>
              </div>
            );
          }
          return (
            <div key={entry.id} className="message user">
              <div className="bubble">{entry.content}</div>
            </div>
          );
        })}

        {busy && (
          <div className="message assistant pending" aria-live="polite">
            <div className="bubble">
              <span className="dot" />
              <span className="dot" />
              <span className="dot" />
            </div>
          </div>
        )}
        <div ref={bottomRef} />
      </main>

      <footer className="footer">
        {simulateFailure && <div className="sim-banner">Next message will simulate: {simulateFailure}</div>}
        <Composer value={draft} onChange={setDraft} onSend={() => send(draft)} busy={busy} />
      </footer>
    </div>
  );
}
