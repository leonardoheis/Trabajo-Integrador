import { describe, it, expect, vi } from "vitest";
import { render, waitFor, screen, fireEvent, act } from "@testing-library/react";
import ChatPage from "./ChatPage";
import * as knowledgeApi from "../api/knowledge";
import * as authApi from "../api/auth";

describe("ChatPage", () => {
  it("fires a warmup request once on mount", async () => {
    const warmupSpy = vi.spyOn(knowledgeApi, "warmupChat").mockResolvedValue();

    render(<ChatPage />);

    await waitFor(() => expect(warmupSpy).toHaveBeenCalledTimes(1));
  });

  it("shows a loading-model message if no token arrives within the timeout, then clears it", async () => {
    vi.spyOn(knowledgeApi, "warmupChat").mockResolvedValue();

    // A stream whose enqueue is controlled from the test, so no token is
    // emitted until we say so.
    let enqueueToken: (() => void) | undefined;
    const encoder = new TextEncoder();
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        enqueueToken = () => {
          controller.enqueue(
            encoder.encode('event: token\ndata: {"text":"hi"}\n\n'),
          );
          controller.close();
        };
      },
    });
    vi.spyOn(authApi, "apiFetch").mockResolvedValue(
      new Response(body, { status: 200 }),
    );

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
});
