import { useState } from "react";
import { apiFetch } from "../api/auth";

interface Source {
  chunkId: string;
  filename: string;
  docType: string;
  number: string;
  year: string;
  subject: string;
  downloadUrl: string;
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

  async function handleSend(): Promise<void> {
    const q = question.trim();
    if (!q || isStreaming) {
      return;
    }
    setQuestion("");
    setMessages((prev) => [
      ...prev,
      { role: "user", content: q },
      { role: "assistant", content: "" },
    ]);
    setIsStreaming(true);

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
        if (done) {
          break;
        }
        buffer += decoder.decode(value, { stream: true });
        const { events, rest } = parseSseEvents(buffer);
        buffer = rest;

        for (const event of events) {
          if (event.type === "token") {
            const { text } = JSON.parse(event.data) as { text: string };
            setMessages((prev) => {
              const next = [...prev];
              const last = next[next.length - 1];
              next[next.length - 1] = { ...last, content: last.content + text };
              return next;
            });
          } else if (event.type === "sources") {
            const sources = JSON.parse(event.data) as Source[];
            setMessages((prev) => {
              const next = [...prev];
              next[next.length - 1] = { ...next[next.length - 1], sources };
              return next;
            });
          } else if (event.type === "error") {
            const { message } = JSON.parse(event.data) as { message: string };
            // The chat UI stays generic (this app's audience is non-technical
            // municipal reviewers) -- the real backend failure is logged here for
            // whoever's debugging, and in full via loguru server-side.
            console.error("chat stream error:", message);
            setMessages((prev) => {
              const next = [...prev];
              next[next.length - 1] = {
                role: "assistant",
                content: "Something went wrong answering that question.",
                error: true,
              };
              return next;
            });
          }
        }
      }
    } catch (err) {
      console.error("chat request failed:", err);
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
              {m.content || (isStreaming && i === messages.length - 1 ? "…" : "")}
            </p>
            {m.sources && m.sources.length > 0 && (
              <ul className="mt-1 space-y-1">
                {m.sources.map((s) => (
                  <li
                    key={s.chunkId}
                    className="font-mono text-[11px] text-[var(--color-text-faint)]"
                  >
                    <a
                      href={s.downloadUrl}
                      target="_blank"
                      rel="noreferrer"
                      className="hover:underline"
                    >
                      {s.filename}
                    </a>{" "}
                    · {s.docType} {s.number}/{s.year} — {s.excerpt}
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
