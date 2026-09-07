import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import ReopenPanel from "./ReopenPanel";

vi.mock("../api/classification", () => ({
  reopenClassification: vi.fn(),
}));

import { reopenClassification } from "../api/classification";

describe("ReopenPanel", () => {
  beforeEach(() => {
    vi.mocked(reopenClassification).mockReset();
  });

  it("will not submit without a reason", () => {
    render(<ReopenPanel jobId="job-1" onReopened={vi.fn()} />);

    expect(screen.getByRole("button", { name: /reopen review/i })).toBeDisabled();
  });

  it("enables submission once a reason is entered", () => {
    render(<ReopenPanel jobId="job-1" onReopened={vi.fn()} />);

    fireEvent.change(screen.getByLabelText("Reason"), {
      target: { value: "wrong label" },
    });

    expect(screen.getByRole("button", { name: /reopen review/i })).toBeEnabled();
  });

  it("treats a whitespace-only reason as empty", () => {
    render(<ReopenPanel jobId="job-1" onReopened={vi.fn()} />);

    fireEvent.change(screen.getByLabelText("Reason"), { target: { value: "   " } });

    expect(screen.getByRole("button", { name: /reopen review/i })).toBeDisabled();
  });

  it("sends the reason and notifies the caller", async () => {
    const onReopened = vi.fn();
    vi.mocked(reopenClassification).mockResolvedValue(undefined);
    render(<ReopenPanel jobId="job-1" onReopened={onReopened} />);

    fireEvent.change(screen.getByLabelText("Reason"), {
      target: { value: "this is a convenio" },
    });
    fireEvent.click(screen.getByRole("button", { name: /reopen review/i }));

    await waitFor(() => expect(onReopened).toHaveBeenCalledOnce());
    expect(reopenClassification).toHaveBeenCalledWith("job-1", "this is a convenio");
  });

  it("surfaces a failure instead of swallowing it", async () => {
    vi.mocked(reopenClassification).mockRejectedValue(new Error("403"));
    render(<ReopenPanel jobId="job-1" onReopened={vi.fn()} />);

    fireEvent.change(screen.getByLabelText("Reason"), { target: { value: "nope" } });
    fireEvent.click(screen.getByRole("button", { name: /reopen review/i }));

    expect(await screen.findByText(/could not reopen/i)).toBeInTheDocument();
  });
});
