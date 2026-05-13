const ENDPOINTS_KEY = "tradingagents_endpoints";

export interface EndpointProfile {
  url: string;
  apiKey?: string;
  deepModel?: string;
  quickModel?: string;
}

export function loadEndpoints(): EndpointProfile[] {
  try {
    return JSON.parse(localStorage.getItem(ENDPOINTS_KEY) ?? "[]");
  } catch {
    return [];
  }
}

export function saveEndpoint(ep: EndpointProfile) {
  const list = loadEndpoints();
  const idx = list.findIndex((e) => e.url === ep.url);
  if (idx >= 0) list[idx] = ep;
  else list.push(ep);
  localStorage.setItem(ENDPOINTS_KEY, JSON.stringify(list));
}

export function removeEndpoint(url: string) {
  const list = loadEndpoints().filter((e) => e.url !== url);
  localStorage.setItem(ENDPOINTS_KEY, JSON.stringify(list));
}
