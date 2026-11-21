import type { ChatMetadata } from "../api";

interface Props {
  content: string;
  metadata: ChatMetadata;
}

export function AssistantMessage({ content, metadata }: Props) {
  const cached = metadata.resolution_source === "LLM_CACHE";

  return (
    <div className="message assistant" data-testid="assistant-message">
      <div className="bubble">{content}</div>
      <div className="meta">
        <span className={`badge ${cached ? "badge-cache" : "badge-live"}`} data-testid="meta-source">
          {metadata.resolution_source}
        </span>
        <span className="meta-item" title="Model">
          <span data-testid="meta-model">{metadata.model}</span>
        </span>
        <span className="meta-item" title="Server-measured latency">
          <span data-testid="meta-latency">{metadata.latency_ms} ms</span>
        </span>
        <span className="meta-item" title="Tokens for this request only">
          in <span data-testid="meta-input-tokens">{metadata.input_tokens}</span>
          {" · "}
          out <span data-testid="meta-output-tokens">{metadata.output_tokens}</span>
        </span>
        {metadata.key_id && (
          <span className="meta-item" title="Key that answered">
            {metadata.key_id}
            {metadata.fallback_attempts > 0 && (
              <span className="fallback">
                {" "}
                after {metadata.fallback_attempts} failover{metadata.fallback_attempts > 1 ? "s" : ""}
              </span>
            )}
          </span>
        )}
      </div>
    </div>
  );
}
