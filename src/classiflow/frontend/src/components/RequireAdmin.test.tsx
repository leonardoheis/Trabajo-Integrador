import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Routes, Route } from "react-router";
import RequireAdmin from "./RequireAdmin";

vi.mock("../auth/AuthContext", () => ({
  useAuth: vi.fn(),
}));

import { useAuth } from "../auth/AuthContext";

describe("RequireAdmin", () => {
  it("redirects non-admins to /", () => {
    vi.mocked(useAuth).mockReturnValue({
      user: { email: "u@example.com", isAdmin: false },
      isAdmin: false,
      isLoading: false,
      login: vi.fn(),
      logout: vi.fn(),
    });

    render(
      <MemoryRouter initialEntries={["/audit"]}>
        <Routes>
          <Route element={<RequireAdmin />}>
            <Route path="/audit" element={<p>Audit page</p>} />
          </Route>
          <Route path="/" element={<p>Home</p>} />
        </Routes>
      </MemoryRouter>,
    );

    expect(screen.getByText("Home")).toBeInTheDocument();
    expect(screen.queryByText("Audit page")).not.toBeInTheDocument();
  });

  it("renders the protected route for admins", () => {
    vi.mocked(useAuth).mockReturnValue({
      user: { email: "a@example.com", isAdmin: true },
      isAdmin: true,
      isLoading: false,
      login: vi.fn(),
      logout: vi.fn(),
    });

    render(
      <MemoryRouter initialEntries={["/audit"]}>
        <Routes>
          <Route element={<RequireAdmin />}>
            <Route path="/audit" element={<p>Audit page</p>} />
          </Route>
        </Routes>
      </MemoryRouter>,
    );

    expect(screen.getByText("Audit page")).toBeInTheDocument();
  });
});
