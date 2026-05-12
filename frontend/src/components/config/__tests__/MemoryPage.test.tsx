import { describe, it, expect, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryPage } from "../MemoryPage";

vi.mock("@/api/client", () => ({
  apiClient: {
    getMemory: vi.fn().mockResolvedValue({ items: [], total: 0, page: 1 }),
  },
}));

function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
}

describe("MemoryPage", () => {
  it("renders memory page heading", () => {
    render(<MemoryPage />, { wrapper: createWrapper() });
    expect(screen.getByRole("heading", { name: /memory/i })).toBeInTheDocument();
  });

  it("shows empty state when no memories", async () => {
    render(<MemoryPage />, { wrapper: createWrapper() });
    await waitFor(() => {
      expect(screen.getByText(/no memories yet/i)).toBeInTheDocument();
    });
  });
});
