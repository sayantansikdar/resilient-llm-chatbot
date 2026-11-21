import { useEffect, useRef } from "react";
import { CheckIcon } from "./icons";

interface Props {
  open: boolean;
  onClose: () => void;
  systemPrompt: string;
  onSystemPromptChange: (value: string) => void;
  simulateFailure: string;
  onSimulateFailureChange: (value: string) => void;
  simulationAvailable: boolean;
}

const SIMULATION_PRESETS = [
  { value: "", label: "Off", detail: "Normal requests" },
  { value: "key_1=429", label: "key_1 rate-limited", detail: "429 → answered by key_2" },
  { value: "key_1=500", label: "key_1 server error", detail: "500 → answered by key_2" },
  { value: "*=429", label: "Every key fails", detail: "503 all providers unavailable" },
];

// A popover that grows out of the settings button (transform-origin top right)
// and goes back the same way.
export function SettingsPanel({
  open,
  onClose,
  systemPrompt,
  onSystemPromptChange,
  simulateFailure,
  onSimulateFailureChange,
  simulationAvailable,
}: Props) {
  const promptRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    const t = window.setTimeout(() => promptRef.current?.focus(), 60);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.clearTimeout(t);
    };
  }, [open, onClose]);

  return (
    <>
      <div className={`scrim ${open ? "open" : ""}`} onClick={onClose} aria-hidden />
      <section
        className={`popover ${open ? "open" : ""}`}
        role="dialog"
        aria-label="Chat settings"
        aria-hidden={!open}
        inert={!open}
      >
        <div className="popover-head">
          <h2>Settings</h2>
          <button className="text-button" onClick={onClose}>
            Done
          </button>
        </div>

        <p className="group-label">System prompt</p>
        <div className="group">
          <textarea
            ref={promptRef}
            data-testid="system-prompt-input"
            className="group-textarea"
            rows={3}
            placeholder="Server default"
            value={systemPrompt}
            onChange={(e) => onSystemPromptChange(e.target.value)}
          />
        </div>
        <p className="group-footer">Applies to this chat from your next message. Clear it to go back to the default.</p>

        <p className="group-label">Failover drill</p>
        <div className={`group ${simulationAvailable ? "" : "disabled"}`} role="radiogroup" aria-label="Simulate key failure">
          {SIMULATION_PRESETS.map((p) => {
            const selected = simulateFailure === p.value;
            return (
              <button
                key={p.value || "off"}
                className="group-row"
                role="radio"
                aria-checked={selected}
                disabled={!simulationAvailable}
                onClick={() => onSimulateFailureChange(p.value)}
              >
                <span className="row-text">
                  <span>{p.label}</span>
                  <span className="row-detail">{p.detail}</span>
                </span>
                <span className="row-check">{selected && <CheckIcon />}</span>
              </button>
            );
          })}
        </div>
        <p className="group-footer">
          {simulationAvailable
            ? "Sends X-Simulate-Failure with the next message only."
            : "Turned off on the server (ENABLE_FAILURE_SIMULATION)."}
        </p>
      </section>
    </>
  );
}
