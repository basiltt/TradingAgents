import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import {
  createRouter,
  createMemoryHistory,
  RouterProvider,
} from "@tanstack/react-router";
import { Provider } from "react-redux";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { configureStore } from "@reduxjs/toolkit";
import { routeTree } from "../route-tree";
import { analysisSlice } from "@/store/analysis-slice";
import { uiSlice } from "@/store/ui-slice";

function renderWithRouter(initialPath: string) {
  const store = configureStore({
    reducer: { analysis: analysisSlice.reducer, ui: uiSlice.reducer },
  });
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const router = createRouter({
    routeTree,
    history: createMemoryHistory({ initialEntries: [initialPath] }),
  });
  return render(
    <Provider store={store}>
      <QueryClientProvider client={queryClient}>
        <RouterProvider router={router} />
      </QueryClientProvider>
    </Provider>,
  );
}

describe("routing", () => {
  it("renders home page at /", async () => {
    renderWithRouter("/");
    expect(
      await screen.findByRole("heading", { name: /autonomous trading research/i }),
    ).toBeInTheDocument();
  });

  it("renders 404 for unknown route", async () => {
    renderWithRouter("/unknown-path-xyz");
    expect(await screen.findByText(/not found/i)).toBeInTheDocument();
  });

  it("renders analysis new page", async () => {
    renderWithRouter("/analysis/new");
    expect(
      await screen.findByRole("heading", { name: /new analysis run/i }),
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
      await screen.findByRole("heading", { name: /historical decisions/i }),
    ).toBeInTheDocument();
  });

  it("renders analysis run page with param", async () => {
    renderWithRouter("/analysis/abc-123");
    expect(
      await screen.findByRole("heading", { name: /analysis/i }),
    ).toBeInTheDocument();
  });

  it("sidebar has accessible label", async () => {
    renderWithRouter("/");
    expect(
      await screen.findByRole("complementary", { name: /primary navigation/i }),
    ).toBeInTheDocument();
  });
});
