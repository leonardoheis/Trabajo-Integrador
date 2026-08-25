import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import ReclassifyPanel from "./ReclassifyPanel";
import * as classificationApi from "../api/classification";

describe("ReclassifyPanel", () => {
  it("submits the selected label and notes", async () => {
    const submitSpy = vi.spyOn(classificationApi, "submitReclassification").mockResolvedValue();

    render(<ReclassifyPanel jobId="job-1" onSubmitted={() => {}} />);

    fireEvent.change(screen.getByLabelText("Label"), { target: { value: "ordenanzas" } });
    fireEvent.change(screen.getByLabelText("Notes"), { target: { value: "manual fix" } });
    fireEvent.click(screen.getByText("Submit"));

    await waitFor(() => {
      expect(submitSpy).toHaveBeenCalledWith("job-1", "ordenanzas", "manual fix");
    });
  });

  it("calls onSubmitted after a successful submission", async () => {
    vi.spyOn(classificationApi, "submitReclassification").mockResolvedValue();
    const onSubmitted = vi.fn();

    render(<ReclassifyPanel jobId="job-1" onSubmitted={onSubmitted} />);
    fireEvent.click(screen.getByText("Submit"));

    await waitFor(() => {
      expect(onSubmitted).toHaveBeenCalled();
    });
  });
});
