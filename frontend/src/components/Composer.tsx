import { useEffect, useRef, type FormEvent, type KeyboardEvent } from "react";
import { ArrowUpIcon } from "./icons";

const MAX_CHARS = 4000;

interface Props {
  value: string;
  onChange: (value: string) => void;
  onSend: () => void;
  busy: boolean;
}

export function Composer({ value, onChange, onSend, busy }: Props) {
  const ref = useRef<HTMLTextAreaElement>(null);
  const length = value.trim().length;
  const tooLong = length > MAX_CHARS;
  const canSend = !busy && length > 0 && !tooLong;

  // grow with the content, up to the CSS max-height
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${el.scrollHeight}px`;
  }, [value]);

  useEffect(() => {
    if (!busy) ref.current?.focus();
  }, [busy]);

  function submit(e?: FormEvent) {
    e?.preventDefault();
    if (canSend) onSend();
  }

  function onKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      submit();
    }
  }

  return (
    <form className="composer" onSubmit={submit}>
      <div className={`field-pill ${tooLong ? "invalid" : ""}`}>
        <textarea
          ref={ref}
          data-testid="chat-input"
          rows={1}
          placeholder="Message"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={onKeyDown}
          aria-label="Message"
        />
        {length > MAX_CHARS * 0.8 && (
          <span className={`counter ${tooLong ? "over" : ""}`}>
            {length}/{MAX_CHARS}
          </span>
        )}
        <button
          type="submit"
          className="send"
          data-testid="send-button"
          disabled={!canSend}
          aria-label={busy ? "Sending" : "Send"}
          title="Send (Enter)"
        >
          <ArrowUpIcon />
        </button>
      </div>
    </form>
  );
}
