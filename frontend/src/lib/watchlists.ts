import { readJson, writeJson } from "./storage";

const STORAGE_KEY = "tradingagents_watchlists";
const MAX_TICKERS = 10;

export interface Watchlist {
  id: string;
  name: string;
  tickers: string[];
}

export function loadWatchlists(): Watchlist[] {
  return readJson<Watchlist[]>(STORAGE_KEY, []);
}

function save(lists: Watchlist[]) {
  writeJson(STORAGE_KEY, lists);
}

export function createWatchlist(name: string): Watchlist[] {
  const lists = loadWatchlists();
  lists.push({ id: crypto.randomUUID(), name, tickers: [] });
  save(lists);
  return lists;
}

export function deleteWatchlist(id: string): Watchlist[] {
  const lists = loadWatchlists().filter((w) => w.id !== id);
  save(lists);
  return lists;
}

export function renameWatchlist(id: string, name: string): Watchlist[] {
  const lists = loadWatchlists();
  const wl = lists.find((w) => w.id === id);
  if (wl) wl.name = name;
  save(lists);
  return lists;
}

export function addTicker(id: string, ticker: string): Watchlist[] {
  const lists = loadWatchlists();
  const wl = lists.find((w) => w.id === id);
  if (wl && !wl.tickers.includes(ticker) && wl.tickers.length < MAX_TICKERS) {
    wl.tickers.push(ticker);
  }
  save(lists);
  return lists;
}

export function removeTicker(id: string, ticker: string): Watchlist[] {
  const lists = loadWatchlists();
  const wl = lists.find((w) => w.id === id);
  if (wl) wl.tickers = wl.tickers.filter((t) => t !== ticker);
  save(lists);
  return lists;
}
