import { describe, it, expect, vi } from "vitest";
import { render, waitFor, screen, fireEvent, act } from "@testing-library/react";
import ChatPage from "./ChatPage";
import * as knowledgeApi from "../api/knowledge";
import * as authApi from "../api/auth";

describe("ChatPage", () => {
  it("fires a warmup request once on mount", async () => {
    const warmupSpy = vi.spyOn(knowledgeApi, "warmupChat").mockResolvedValue();
    vi.spyOn(knowledgeApi, "fetchConversation").mockResolvedValue({ summary: null, turns: [] });

    render(<ChatPage />);

    await waitFor(() => expect(warmupSpy).toHaveBeenCalledTimes(1));
  });

  it("shows a loading-model message if no token arrives within the timeout, then clears it", async () => {
    vi.spyOn(knowledgeApi, "warmupChat").mockResolvedValue();
    vi.spyOn(knowledgeApi, "fetchConversation").mockResolvedValue({ summary: null, turns: [] });

    // A stream whose enqueue is controlled from the test, so no token is
    // emitted until we say so.
    let enqueueToken: (() => void) | undefined;
    const encoder = new TextEncoder();
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        enqueueToken = () => {
          controller.enqueue(encoder.encode('event: token\ndata: {"text":"hi"}\n\n'));
          controller.close();
        };
      },
    });
    vi.spyOn(authApi, "apiFetch").mockResolvedValue(new Response(body, { status: 200 }));

    vi.useFakeTimers();
    try {
      render(<ChatPage />);

      const input = screen.getByPlaceholderText(/ask a question/i);
      fireEvent.change(input, { target: { value: "hello?" } });
      await act(async () => {
        fireEvent.click(screen.getByRole("button", { name: /send/i }));
      });

      await act(async () => {
        await vi.advanceTimersByTimeAsync(1500);
      });
      expect(screen.getByText("Cargando modelo, puede tardar unos segundos…")).toBeInTheDocument();

      await act(async () => {
        enqueueToken?.();
        await vi.advanceTimersByTimeAsync(0);
      });
      expect(screen.getByText("hi")).toBeInTheDocument();
      expect(
        screen.queryByText("Cargando modelo, puede tardar unos segundos…"),
      ).not.toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });

  it("loads and renders prior conversation history on mount", async () => {
    vi.spyOn(knowledgeApi, "warmupChat").mockResolvedValue();
    vi.spyOn(knowledgeApi, "fetchConversation").mockResolvedValue({
      summary: null,
      turns: [{ question: "pregunta previa", answer: "respuesta previa", createdAt: "2026-01-01" }],
    });

    render(<ChatPage />);

    await waitFor(() => expect(screen.getByText("pregunta previa")).toBeInTheDocument());
    expect(screen.getByText("respuesta previa")).toBeInTheDocument();
  });

  it("clears the visible history when Clear conversation is clicked", async () => {
    vi.spyOn(knowledgeApi, "warmupChat").mockResolvedValue();
    vi.spyOn(knowledgeApi, "fetchConversation").mockResolvedValue({
      summary: null,
      turns: [{ question: "pregunta previa", answer: "respuesta previa", createdAt: "2026-01-01" }],
    });
    const clearSpy = vi.spyOn(knowledgeApi, "clearConversation").mockResolvedValue();

    render(<ChatPage />);
    await waitFor(() => expect(screen.getByText("pregunta previa")).toBeInTheDocument());

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /clear conversation/i }));
    });

    expect(clearSpy).toHaveBeenCalledTimes(1);
    expect(screen.queryByText("pregunta previa")).not.toBeInTheDocument();
  });
});
