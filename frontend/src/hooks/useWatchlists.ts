import { useState, useCallback } from "react";
import {
  loadWatchlists,
  createWatchlist as createWl,
  deleteWatchlist as deleteWl,
  renameWatchlist as renameWl,
  addTicker as addT,
  removeTicker as removeT,
  type Watchlist,
} from "@/lib/watchlists";

export function useWatchlists() {
  const [watchlists, setWatchlists] = useState<Watchlist[]>(loadWatchlists);

  const create = useCallback((name: string) => setWatchlists(createWl(name)), []);
  const remove = useCallback((id: string) => setWatchlists(deleteWl(id)), []);
  const rename = useCallback((id: string, name: string) => setWatchlists(renameWl(id, name)), []);
  const addTicker = useCallback((id: string, ticker: string) => setWatchlists(addT(id, ticker)), []);
  const removeTicker = useCallback((id: string, ticker: string) => setWatchlists(removeT(id, ticker)), []);

  return { watchlists, create, remove, rename, addTicker, removeTicker };
}
