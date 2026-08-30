import { describe, it, expect, vi } from "vitest";
import { render, waitFor } from "@testing-library/react";
import ChatPage from "./ChatPage";
import * as knowledgeApi from "../api/knowledge";

describe("ChatPage", () => {
  it("fires a warmup request once on mount", async () => {
    const warmupSpy = vi.spyOn(knowledgeApi, "warmupChat").mockResolvedValue();

    render(<ChatPage />);

    await waitFor(() => expect(warmupSpy).toHaveBeenCalledTimes(1));
  });
});
