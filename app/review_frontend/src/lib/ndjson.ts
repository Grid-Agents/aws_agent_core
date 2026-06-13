import type { AgentEvent } from "../types";

/**
 * Consume a streaming NDJSON response (the same trace/result event stream the
 * Grid agent emits), invoking `onEvent` for each parsed line as it arrives.
 */
export async function streamNDJSON(
  resp: Response,
  onEvent: (ev: AgentEvent) => void,
): Promise<void> {
  if (!resp.body) throw new Error("response has no body to stream");
  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  const flushLine = (line: string) => {
    const trimmed = line.trim();
    if (!trimmed) return;
    try {
      onEvent(JSON.parse(trimmed) as AgentEvent);
    } catch {
      /* ignore partial / non-JSON lines */
    }
  };

  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let nl: number;
    while ((nl = buffer.indexOf("\n")) >= 0) {
      flushLine(buffer.slice(0, nl));
      buffer = buffer.slice(nl + 1);
    }
  }
  flushLine(buffer);
}
