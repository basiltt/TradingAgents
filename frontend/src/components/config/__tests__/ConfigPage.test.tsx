import { describe, it, expect, beforeAll, afterAll, afterEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { Provider } from "react-redux";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { configureStore } from "@reduxjs/toolkit";
import { analysisSlice } from "@/store/analysis-slice";
import { uiSlice } from "@/store/ui-slice";
import { ConfigPage } from "../ConfigPage";

const server = setupServer(
  http.get("/api/v1/config", () =>
    HttpResponse.json({
      defaults: { llm_provider: "openai" },
      resolved: { llm_provider: "openai", deep_think_llm: "gpt-4o" },
      overrides: {},
    }),
  ),
  http.patch("/api/v1/config", async ({ request }) => {
    const body = (await request.json()) as Record<string, unknown>;
    return HttpResponse.json({
      defaults: { llm_provider: "openai" },
      resolved: { ...body.overrides as object },
      overrides: body.overrides,
    });
  }),
);

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

function createWrapper() {
  const store = configureStore({
    reducer: { analysis: analysisSlice.reducer, ui: uiSlice.reducer },
  });
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return ({ children }: { children: React.ReactNode }) => (
    <Provider store={store}>
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    </Provider>
  );
}

describe("ConfigPage", () => {
  it("loads and displays config", async () => {
    render(<ConfigPage />, { wrapper: createWrapper() });
    expect(await screen.findByText(/llm_provider/i)).toBeInTheDocument();
    expect(screen.getByText(/openai/)).toBeInTheDocument();
  });

  it("shows loading state", () => {
    render(<ConfigPage />, { wrapper: createWrapper() });
    expect(screen.getByText(/loading/i)).toBeInTheDocument();
  });

  it("shows error on fetch failure", async () => {
    server.use(
      http.get("/api/v1/config", () =>
        HttpResponse.json({ detail: "Server error" }, { status: 500 }),
      ),
    );
    render(<ConfigPage />, { wrapper: createWrapper() });
    expect(await screen.findByText(/error/i)).toBeInTheDocument();
  });
});
