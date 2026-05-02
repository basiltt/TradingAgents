import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import {
  createRouter,
  createMemoryHistory,
  RouterProvider,
} from "@tanstack/react-router";
import { routeTree } from "../route-tree";

function renderWithRouter(initialPath: string) {
  const router = createRouter({
    routeTree,
    history: createMemoryHistory({ initialEntries: [initialPath] }),
  });
  return render(<RouterProvider router={router} />);
}

describe("routing", () => {
  it("renders home page at /", async () => {
    renderWithRouter("/");
    expect(
      await screen.findByRole("heading", { name: /dashboard/i }),
    ).toBeInTheDocument();
  });

  it("renders 404 for unknown route", async () => {
    renderWithRouter("/unknown-path-xyz");
    expect(await screen.findByText(/not found/i)).toBeInTheDocument();
  });

  it("renders analysis new page", async () => {
    renderWithRouter("/analysis/new");
    expect(
      await screen.findByRole("heading", { name: /new analysis/i }),
    ).toBeInTheDocument();
  });

  it("renders config page", async () => {
    renderWithRouter("/config");
    expect(
      await screen.findByRole("heading", { name: /configuration/i }),
    ).toBeInTheDocument();
  });

  it("renders history page", async () => {
    renderWithRouter("/history");
    expect(
      await screen.findByRole("heading", { name: /history/i }),
    ).toBeInTheDocument();
  });

  it("renders memory page", async () => {
    renderWithRouter("/memory");
    expect(
      await screen.findByRole("heading", { name: /memory/i }),
    ).toBeInTheDocument();
  });
});
