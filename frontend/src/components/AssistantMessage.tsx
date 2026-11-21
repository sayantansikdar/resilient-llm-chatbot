import type { ChatMetadata } from "../api";

interface Props {
  content: string;
  metadata: ChatMetadata;
}

export function AssistantMessage({ content, metadata }: Props) {
  const cached = metadata.resolution_source === "LLM_CACHE";

  return (
    <div className="row row-in" data-testid="assistant-message">
      <div className="bubble bubble-in">{content}</div>
      <div className="caption">
        <span className={`capsule ${cached ? "capsule-cache" : "capsule-live"}`} data-testid="meta-source">
          {metadata.resolution_source}
        </span>
        <span data-testid="meta-model">{metadata.model}</span>
        <span className="sep" aria-hidden>·</span>
        <span data-testid="meta-latency">{metadata.latency_ms} ms</span>
        <span className="sep" aria-hidden>·</span>
        <span title="Tokens for this request only">
          <span data-testid="meta-input-tokens">{metadata.input_tokens}</span> in{" / "}
          <span data-testid="meta-output-tokens">{metadata.output_tokens}</span> out
        </span>
        {metadata.key_id && (
          <>
            <span className="sep" aria-hidden>·</span>
            <span title="Key that answered">
              {metadata.key_id}
              {metadata.fallback_attempts > 0 && (
                <span className="failover">
                  {" "}after {metadata.fallback_attempts} failover{metadata.fallback_attempts > 1 ? "s" : ""}
                </span>
              )}
            </span>
          </>
        )}
      </div>
    </div>
  );
}
