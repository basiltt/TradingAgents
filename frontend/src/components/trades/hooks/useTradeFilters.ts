import { useEffect, useCallback } from "react";
import { useNavigate, useSearch } from "@tanstack/react-router";
import { useDebouncedCallback } from "use-debounce";
import { useAppDispatch, useAppSelector } from "@/store";
import { setFilters, setActiveTab } from "@/store/trades-slice";
import type { TradeFilters } from "@/components/trades/types";

function filtersToSearchParams(filters: Partial<TradeFilters>) {
  const params: Record<string, string> = {};
  if (filters.account_ids?.length) params.account_id = filters.account_ids.join(",");
  if (filters.symbol) params.symbol = filters.symbol;
  if (filters.side) params.side = filters.side;
  if (filters.from_date) params.from_date = filters.from_date;
  if (filters.to_date) params.to_date = filters.to_date;
  return params;
}

export function useTradeFilters() {
  const dispatch = useAppDispatch();
  const filters = useAppSelector((s) => s.trades.filters);
  const activeTab = useAppSelector((s) => s.trades.activeTab);
  const navigate = useNavigate();

  let search: Record<string, string | undefined> = {};
  try {
    search = useSearch({ strict: false }) as Record<string, string | undefined>;
  } catch {
    // outside router context
  }

  useEffect(() => {
    const urlFilters: Partial<TradeFilters> = {};
    if (search.account_id) urlFilters.account_ids = search.account_id.split(",");
    if (search.symbol) urlFilters.symbol = search.symbol;
    if (search.side) urlFilters.side = search.side;
    if (search.from_date) urlFilters.from_date = search.from_date;
    if (search.to_date) urlFilters.to_date = search.to_date;
    if (Object.keys(urlFilters).length > 0) {
      dispatch(setFilters(urlFilters));
    }
    if (search.tab === "active" || search.tab === "history") {
      dispatch(setActiveTab(search.tab));
    }
  }, [search.account_id, search.symbol, search.side, search.from_date, search.to_date, search.tab, dispatch]);

  const updateFilters = useDebouncedCallback((newFilters: Partial<TradeFilters>) => {
    dispatch(setFilters(newFilters));
    navigate({
      search: {
        ...search,
        ...filtersToSearchParams(newFilters),
      },
    });
  }, 300);

  const clearFilters = useCallback(() => {
    dispatch(
      setFilters({
        account_ids: [],
        status: [],
        symbol: "",
        side: "",
        from_date: "",
        to_date: "",
      }),
    );
    navigate({ search: { tab: activeTab } });
  }, [dispatch, navigate, activeTab]);

  return { filters, activeTab, updateFilters, clearFilters };
}
