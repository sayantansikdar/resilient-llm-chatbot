import { useEffect, useRef, type FormEvent, type KeyboardEvent } from "react";

const MAX_CHARS = 4000;

interface Props {
  value: string;
  onChange: (value: string) => void;
  onSend: () => void;
  busy: boolean;
}

export function Composer({ value, onChange, onSend, busy }: Props) {
  const ref = useRef<HTMLTextAreaElement>(null);
  const tooLong = value.trim().length > MAX_CHARS;
  const canSend = !busy && value.trim().length > 0 && !tooLong;

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
      <textarea
        ref={ref}
        data-testid="chat-input"
        rows={1}
        placeholder="Message the assistant…  (Enter to send, Shift+Enter for a new line)"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={onKeyDown}
        aria-label="Message"
      />
      <div className="composer-side">
        {value.length > MAX_CHARS * 0.8 && (
          <span className={`counter ${tooLong ? "over" : ""}`}>
            {value.trim().length}/{MAX_CHARS}
          </span>
        )}
        <button type="submit" data-testid="send-button" disabled={!canSend}>
          {busy ? "Sending…" : "Send"}
        </button>
      </div>
    </form>
  );
}
