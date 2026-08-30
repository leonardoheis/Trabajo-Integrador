import { useEffect, useState } from "react";
import { apiFetch } from "../api/auth";
import { warmupChat } from "../api/knowledge";

const _COLD_START_MS = 1500;

interface Source {
  chunkId: string;
  filename: string;
  docType: string;
  number: string;
  year: string;
  excerpt: string;
  score: number;
}

interface Message {
  role: "user" | "assistant";
  content: string;
  sources?: Source[];
  error?: boolean;
}

function parseSseEvents(buffer: string): {
  events: { type: string; data: string }[];
  rest: string;
} {
  const events: { type: string; data: string }[] = [];
  const chunks = buffer.split("\n\n");
  const rest = chunks.pop() ?? "";
  for (const chunk of chunks) {
    const lines = chunk.split("\n");
    const eventLine = lines.find((l) => l.startsWith("event: "));
    const dataLine = lines.find((l) => l.startsWith("data: "));
    if (eventLine && dataLine) {
      events.push({
        type: eventLine.slice("event: ".length),
        data: dataLine.slice("data: ".length),
      });
    }
  }
  return { events, rest };
}

export default function ChatPage() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [question, setQuestion] = useState("");
  const [isStreaming, setIsStreaming] = useState(false);
  const [coldStart, setColdStart] = useState(false);

  useEffect(() => {
    warmupChat().catch(() => {});
  }, []);

  async function handleSend(): Promise<void> {
    const q = question.trim();
    if (!q || isStreaming) return;
    setQuestion("");
    setMessages((prev) => [
      ...prev,
      { role: "user", content: q },
      { role: "assistant", content: "" },
    ]);
    setIsStreaming(true);
    const coldStartTimer = setTimeout(() => setColdStart(true), _COLD_START_MS);

    try {
      const response = await apiFetch("/knowledge/chat/stream", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: q }),
      });
      if (!response.ok || !response.body) {
        throw new Error(`POST /knowledge/chat/stream failed: ${response.status}`);
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const { events, rest } = parseSseEvents(buffer);
        buffer = rest;

        for (const event of events) {
          if (event.type === "token") {
            clearTimeout(coldStartTimer);
            setColdStart(false);
            const { text } = JSON.parse(event.data) as { text: string };
            setMessages((prev) => {
              const next = [...prev];
              next[next.length - 1] = {
                ...next[next.length - 1],
                content: next[next.length - 1].content + text,
              };
              return next;
            });
          } else if (event.type === "sources") {
            const sources = JSON.parse(event.data) as Source[];
            setMessages((prev) => {
              const next = [...prev];
              next[next.length - 1] = { ...next[next.length - 1], sources };
              return next;
            });
          }
        }
      }
    } catch {
      setMessages((prev) => {
        const next = [...prev];
        next[next.length - 1] = {
          role: "assistant",
          content: "Something went wrong answering that question.",
          error: true,
        };
        return next;
      });
    } finally {
      clearTimeout(coldStartTimer);
      setIsStreaming(false);
    }
  }

  return (
    <div className="flex h-full flex-col p-6">
      <h1 className="mb-4 text-xl font-bold text-[var(--color-text)]">Chat</h1>
      <div className="flex-1 space-y-4 overflow-y-auto">
        {messages.map((m, i) => (
          <div key={i} className={m.role === "user" ? "text-right" : "text-left"}>
            <p
              className={`inline-block max-w-[75%] rounded-md px-3 py-2 text-sm ${
                m.role === "user"
                  ? "bg-[var(--color-accent)] text-[var(--color-bg)]"
                  : m.error
                    ? "bg-[var(--color-surface)] text-[var(--color-danger)]"
                    : "bg-[var(--color-surface)] text-[var(--color-text)]"
              }`}
            >
              {m.content ||
                (isStreaming && i === messages.length - 1
                  ? coldStart
                    ? "Cargando modelo, puede tardar unos segundos…"
                    : "…"
                  : "")}
            </p>
            {m.sources && m.sources.length > 0 && (
              <ul className="mt-1 space-y-1">
                {m.sources.map((s) => (
                  <li
                    key={s.chunkId}
                    className="font-mono text-[11px] text-[var(--color-text-faint)]"
                  >
                    {s.filename} · {s.docType} {s.number}/{s.year} — {s.excerpt}
                  </li>
                ))}
              </ul>
            )}
          </div>
        ))}
      </div>
      <div className="mt-4 flex gap-2">
        <input
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && handleSend()}
          placeholder="Ask a question about the indexed documents…"
          disabled={isStreaming}
          className="flex-1 rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] p-2 text-sm text-[var(--color-text)] placeholder:text-[var(--color-text-faint)]"
        />
        <button
          onClick={handleSend}
          disabled={isStreaming || !question.trim()}
          className="rounded-md bg-[var(--color-accent)] px-4 py-2 text-sm font-semibold text-[var(--color-bg)] disabled:opacity-50"
        >
          Send
        </button>
      </div>
    </div>
  );
}
