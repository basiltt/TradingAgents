export interface ModelOption {
  label: string;
  value: string;
}

export type ModelMode = "quick" | "deep";

const MODEL_OPTIONS: Record<string, Record<ModelMode, ModelOption[]>> = {
  openai: {
    quick: [
      { label: "GPT-5.4 Mini — Fast, strong coding", value: "gpt-5.4-mini" },
      { label: "GPT-5.4 Nano — Cheapest", value: "gpt-5.4-nano" },
      { label: "GPT-5.4 — Frontier, 1M context", value: "gpt-5.4" },
      { label: "GPT-4.1 — Smartest non-reasoning", value: "gpt-4.1" },
    ],
    deep: [
      { label: "GPT-5.4 — Frontier, 1M context", value: "gpt-5.4" },
      { label: "GPT-5.2 — Strong reasoning", value: "gpt-5.2" },
      { label: "GPT-5.4 Mini — Fast, strong coding", value: "gpt-5.4-mini" },
      { label: "GPT-5.4 Pro — Most capable", value: "gpt-5.4-pro" },
    ],
  },
  anthropic: {
    quick: [
      { label: "Claude Sonnet 4.6", value: "claude-sonnet-4-6" },
      { label: "Claude Haiku 4.5", value: "claude-haiku-4-5" },
      { label: "Claude Sonnet 4.5", value: "claude-sonnet-4-5" },
    ],
    deep: [
      { label: "Claude Opus 4.6", value: "claude-opus-4-6" },
      { label: "Claude Opus 4.5", value: "claude-opus-4-5" },
      { label: "Claude Sonnet 4.6", value: "claude-sonnet-4-6" },
      { label: "Claude Sonnet 4.5", value: "claude-sonnet-4-5" },
    ],
  },
  google: {
    quick: [
      { label: "Gemini 3 Flash", value: "gemini-3-flash-preview" },
      { label: "Gemini 2.5 Flash", value: "gemini-2.5-flash" },
    ],
    deep: [
      { label: "Gemini 3.1 Pro", value: "gemini-3.1-pro-preview" },
      { label: "Gemini 3 Flash", value: "gemini-3-flash-preview" },
      { label: "Gemini 2.5 Pro", value: "gemini-2.5-pro" },
    ],
  },
  deepseek: {
    quick: [
      { label: "DeepSeek V4 Flash", value: "deepseek-v4-flash" },
      { label: "DeepSeek V3.2", value: "deepseek-chat" },
    ],
    deep: [
      { label: "DeepSeek V4 Pro", value: "deepseek-v4-pro" },
      { label: "DeepSeek V3.2 (thinking)", value: "deepseek-reasoner" },
    ],
  },
  nvidia: {
    quick: [
      { label: "DeepSeek V4 Flash (NVIDIA)", value: "deepseek-v4-flash" },
    ],
    deep: [
      { label: "DeepSeek V4 Pro (NVIDIA)", value: "deepseek-v4-pro" },
    ],
  },
  xai: {
    quick: [
      { label: "Grok 4.1 Fast (Non-Reasoning)", value: "grok-4-1-fast-non-reasoning" },
      { label: "Grok 4 Fast (Non-Reasoning)", value: "grok-4-fast-non-reasoning" },
    ],
    deep: [
      { label: "Grok 4", value: "grok-4-0709" },
      { label: "Grok 4.1 Fast (Reasoning)", value: "grok-4-1-fast-reasoning" },
    ],
  },
};

export function getModelOptions(provider: string, mode: ModelMode): ModelOption[] {
  return MODEL_OPTIONS[provider.toLowerCase()]?.[mode] ?? [];
}

export function getAllProviderModels(provider: string): ModelOption[] {
  const p = MODEL_OPTIONS[provider.toLowerCase()];
  if (!p) return [];
  const seen = new Set<string>();
  const result: ModelOption[] = [];
  for (const mode of ["deep", "quick"] as const) {
    for (const opt of p[mode]) {
      if (!seen.has(opt.value)) {
        seen.add(opt.value);
        result.push(opt);
      }
    }
  }
  return result;
}
