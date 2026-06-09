// AI-CONTEXT: SECURITY — API keys are stored in plaintext in localStorage.
// This is intentional: the key is user-provided, user-owned, and only accessible
// to same-origin scripts. The alternative (prompting each session) was rejected
// for UX reasons. Any XSS vulnerability would expose these keys.
import { readJson, writeJson } from "./storage";

const ENDPOINTS_KEY = "tradingagents_endpoints";

export interface EndpointProfile {
  url: string;
  apiKey?: string;
  deepModel?: string;
  quickModel?: string;
}

export function loadEndpoints(): EndpointProfile[] {
  return readJson<EndpointProfile[]>(ENDPOINTS_KEY, []);
}

export function saveEndpoint(ep: EndpointProfile) {
  const list = loadEndpoints();
  const idx = list.findIndex((e) => e.url === ep.url);
  if (idx >= 0) list[idx] = ep;
  else list.push(ep);
  writeJson(ENDPOINTS_KEY, list);
}

export function removeEndpoint(url: string) {
  const list = loadEndpoints().filter((e) => e.url !== url);
  writeJson(ENDPOINTS_KEY, list);
}
