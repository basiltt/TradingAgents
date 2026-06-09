import { describe, it, expect } from "vitest";
import { getModelOptions, getAllProviderModels } from "../model-catalog";

describe("model-catalog", () => {
  describe("getModelOptions", () => {
    it("returns quick models for openai", () => {
      const opts = getModelOptions("openai", "quick");
      expect(opts.length).toBeGreaterThan(0);
      expect(opts[0]).toHaveProperty("label");
      expect(opts[0]).toHaveProperty("value");
    });

    it("returns deep models for anthropic", () => {
      const opts = getModelOptions("anthropic", "deep");
      expect(opts.length).toBeGreaterThan(0);
      expect(opts.some(o => o.value.includes("opus"))).toBe(true);
    });

    it("returns empty array for unknown provider", () => {
      expect(getModelOptions("unknown_provider", "quick")).toEqual([]);
    });

    it("is case-insensitive on provider name", () => {
      expect(getModelOptions("OpenAI", "quick")).toEqual(getModelOptions("openai", "quick"));
    });

    it("returns models for google", () => {
      expect(getModelOptions("google", "deep").length).toBeGreaterThan(0);
    });

    it("returns models for deepseek", () => {
      expect(getModelOptions("deepseek", "quick").length).toBeGreaterThan(0);
    });

    it("returns models for xai", () => {
      expect(getModelOptions("xai", "deep").length).toBeGreaterThan(0);
    });

    it("returns models for nvidia", () => {
      expect(getModelOptions("nvidia", "quick").length).toBeGreaterThan(0);
    });
  });

  describe("getAllProviderModels", () => {
    it("returns deduplicated models from both modes", () => {
      const all = getAllProviderModels("openai");
      const values = all.map(o => o.value);
      const unique = new Set(values);
      expect(values.length).toBe(unique.size);
    });

    it("returns empty array for unknown provider", () => {
      expect(getAllProviderModels("nope")).toEqual([]);
    });

    it("includes models from both quick and deep", () => {
      const all = getAllProviderModels("anthropic");
      const quick = getModelOptions("anthropic", "quick");
      const deep = getModelOptions("anthropic", "deep");
      for (const opt of quick) {
        expect(all.some(a => a.value === opt.value)).toBe(true);
      }
      for (const opt of deep) {
        expect(all.some(a => a.value === opt.value)).toBe(true);
      }
    });
  });

  describe("edge cases", () => {
    it("getModelOptions returns [] for an empty provider string", () => {
      expect(getModelOptions("", "quick")).toEqual([]);
      expect(getModelOptions("", "deep")).toEqual([]);
    });

    it("getModelOptions does not trim — whitespace provider is unknown", () => {
      expect(getModelOptions(" openai ", "quick")).toEqual([]);
    });

    it("getAllProviderModels returns [] for an empty provider string", () => {
      expect(getAllProviderModels("")).toEqual([]);
    });

    it("getAllProviderModels is case-insensitive", () => {
      expect(getAllProviderModels("ANTHROPIC")).toEqual(getAllProviderModels("anthropic"));
    });

    it("orders getAllProviderModels deep-first (first entry is a deep model)", () => {
      const all = getAllProviderModels("openai");
      const deep = getModelOptions("openai", "deep");
      expect(all[0].value).toBe(deep[0].value);
      expect(all[0].value).toBe("gpt-5.4");
    });

    it("dedupes a value shared across deep and quick (keeps the deep entry once)", () => {
      // anthropic: claude-sonnet-4-6 appears in both quick and deep.
      const all = getAllProviderModels("anthropic");
      const shared = all.filter(o => o.value === "claude-sonnet-4-6");
      expect(shared).toHaveLength(1);
    });

    it("appends quick-only models after the deep block", () => {
      // openai quick has gpt-5.4-nano which is absent from deep → must appear, after deep entries.
      const all = getAllProviderModels("openai");
      const values = all.map(o => o.value);
      expect(values).toContain("gpt-5.4-nano");
      expect(values.indexOf("gpt-5.4-nano")).toBeGreaterThan(values.indexOf("gpt-5.4"));
    });

    it("nvidia: distinct deep/quick values both survive dedup", () => {
      const all = getAllProviderModels("nvidia");
      const values = all.map(o => o.value);
      expect(values).toContain("deepseek-v4-pro");
      expect(values).toContain("deepseek-v4-flash");
      expect(values).toHaveLength(2);
    });
  });
});
