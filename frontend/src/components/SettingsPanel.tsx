interface Props {
  systemPrompt: string;
  onSystemPromptChange: (value: string) => void;
  simulateFailure: string;
  onSimulateFailureChange: (value: string) => void;
  simulationAvailable: boolean;
}

const SIMULATION_PRESETS = [
  { value: "", label: "Off" },
  { value: "key_1=429", label: "key_1 → 429 (rate limit)" },
  { value: "key_1=500", label: "key_1 → 500 (server error)" },
  { value: "key_1=503,key_2=502", label: "key_1 → 503, key_2 → 502" },
  { value: "*=429", label: "every key → 429" },
];

export function SettingsPanel({
  systemPrompt,
  onSystemPromptChange,
  simulateFailure,
  onSimulateFailureChange,
  simulationAvailable,
}: Props) {
  return (
    <section className="settings">
      <label className="field">
        <span className="field-label">System prompt</span>
        <textarea
          data-testid="system-prompt-input"
          rows={3}
          placeholder="Leave empty to use the server default. Applies to this session from the next message."
          value={systemPrompt}
          onChange={(e) => onSystemPromptChange(e.target.value)}
        />
      </label>

      <label className="field">
        <span className="field-label">Simulate key failure (next message only)</span>
        <select
          value={simulateFailure}
          disabled={!simulationAvailable}
          onChange={(e) => onSimulateFailureChange(e.target.value)}
        >
          {SIMULATION_PRESETS.map((p) => (
            <option key={p.value} value={p.value}>
              {p.label}
            </option>
          ))}
        </select>
        {!simulationAvailable && (
          <span className="hint">Turned off on the server (ENABLE_FAILURE_SIMULATION).</span>
        )}
      </label>
    </section>
  );
}
