"""Shared library for the signal-accuracy research harness.

Goal: objectively measure whether a trade signal is "good" using REAL historical
data from the local DB, with NO lookahead, so we can iterate on the signal-generation
mechanism and prove accuracy improvements that reproduce.

Data contract (verified Phase 0):
- scan_results: 89k rows, 2,550 actionable (|score|>=6), full decision_summary JSON.
- Anchor time = scans.started_at (TEXT ISO). Conservative no-lookahead: features use
  only klines with open_time < anchor; outcome uses klines with open_time >= anchor.
- kline_cache: interval='5m' is the workhorse (5.43M candles, 587 symbols,
  2026-04-30 .. 2026-06-13). 2,535/2,550 actionable signals have klines both sides.

Outcome labeling = PATH-DEPENDENT trade simulation: walk forward 5m candles from the
entry and decide whether TP or SL is hit first (the honest "would this trade have made
money" question), plus a forward max-favorable/adverse excursion for analysis.
"""
from __future__ import annotations
import asyncio, json, datetime as dt
import asyncpg

LOCAL = "postgresql://postgres:Mywings123@localhost:5432/tradingagents"

# ---- DB helpers -------------------------------------------------------------
async def connect():
    return await asyncpg.connect(LOCAL)

def parse_ts(v) -> dt.datetime:
    if isinstance(v, dt.datetime):
        return v if v.tzinfo else v.replace(tzinfo=dt.timezone.utc)
    return dt.datetime.fromisoformat(str(v).replace("Z", "+00:00"))

# ---- Signal fetch -----------------------------------------------------------
SIGNAL_QUERY = """
    select sr.id, sr.ticker, sr.score, sr.direction, sr.confidence,
           sr.decision_summary, s.started_at as anchor
    from scan_results sr
    join scans s on s.scan_id = sr.scan_id
    where abs(sr.score) >= $1
      and sr.decision_summary is not null and sr.decision_summary != ''
      and s.started_at is not null
"""

async def fetch_signals(conn, min_abs_score=6, limit=400, seed=42):
    """Deterministic pseudo-random sample of actionable signals (reproducible via seed
    in the ORDER BY hash). Only those with klines on both sides of the anchor."""
    rows = await conn.fetch(SIGNAL_QUERY + f"""
      and exists(select 1 from kline_cache k where k.symbol=sr.ticker and k.interval='5m'
                 and k.open_time < s.started_at::timestamptz)
      and exists(select 1 from kline_cache k where k.symbol=sr.ticker and k.interval='5m'
                 and k.open_time >= s.started_at::timestamptz)
      order by md5(sr.id::text || '{seed}')
      limit {limit}
    """, min_abs_score)
    out = []
    for r in rows:
        try:
            ds = json.loads(r["decision_summary"])
        except Exception:
            continue
        out.append({
            "id": r["id"], "ticker": r["ticker"], "score": r["score"],
            "direction": r["direction"], "confidence": r["confidence"],
            "ds": ds, "anchor": parse_ts(r["anchor"]),
        })
    return out

# ---- Klines -----------------------------------------------------------------
async def klines_before(conn, symbol, anchor, n=120, interval="5m"):
    """Up to n candles strictly BEFORE the anchor (features; no lookahead). ASC order."""
    rows = await conn.fetch("""
        select open_time, open::float8 o, high::float8 h, low::float8 l, close::float8 c, volume::float8 v
        from kline_cache where symbol=$1 and interval=$2 and open_time < $3
        order by open_time desc limit $4
    """, symbol, interval, anchor, n)
    return [dict(r) for r in reversed(rows)]

async def klines_after(conn, symbol, anchor, n=96, interval="5m"):
    """Up to n candles AT/AFTER the anchor (outcome window). ASC order. n=96 5m = 8h."""
    rows = await conn.fetch("""
        select open_time, open::float8 o, high::float8 h, low::float8 l, close::float8 c, volume::float8 v
        from kline_cache where symbol=$1 and interval=$2 and open_time >= $3
        order by open_time asc limit $4
    """, symbol, interval, anchor, n)
    return [dict(r) for r in rows]

# ---- Ground-truth outcome labeling -----------------------------------------
def label_outcome(direction, entry, sl, tps, after_klines, horizon=96):
    """Path-dependent trade simulation over forward 5m candles.

    Returns dict with:
      result: 'tp' | 'sl' | 'timeout'  (which was hit FIRST)
      win: bool (tp before sl) — the honest accuracy label
      mfe_pct / mae_pct: max favorable / adverse excursion (%) over the horizon
      r_multiple: realized reward in R (TP1 distance vs SL distance), signed
    A SHORT wins if low reaches TP before high reaches SL; LONG is the mirror.
    """
    if not after_klines or entry is None:
        return None
    is_short = direction in ("sell", "short")
    tp1 = tps[0] if tps else None
    win = None
    result = "timeout"
    mfe = 0.0; mae = 0.0
    for k in after_klines[:horizon]:
        hi, lo = k["h"], k["l"]
        if is_short:
            fav = (entry - lo) / entry * 100   # price down = favorable
            adv = (hi - entry) / entry * 100   # price up = adverse
        else:
            fav = (hi - entry) / entry * 100
            adv = (entry - lo) / entry * 100
        mfe = max(mfe, fav); mae = max(mae, adv)
        # check SL/TP hit this candle (assume adverse-first within a candle = conservative)
        sl_hit = False; tp_hit = False
        if sl:
            sl_hit = (hi >= sl) if is_short else (lo <= sl)
        if tp1:
            tp_hit = (lo <= tp1) if is_short else (hi >= tp1)
        if sl_hit and tp_hit:
            result = "sl"; win = False; break          # conservative: SL first
        if sl_hit:
            result = "sl"; win = False; break
        if tp_hit:
            result = "tp"; win = True; break
    if win is None:
        # timeout: judge by final close direction
        final = after_klines[min(horizon, len(after_klines)) - 1]["c"]
        win = (final < entry) if is_short else (final > entry)
        result = "timeout"
    # R multiple
    r_mult = None
    if sl and tp1 and entry:
        risk = abs(entry - sl); reward = abs(tp1 - entry)
        if risk > 0:
            r_mult = (reward / risk) if win else -1.0
    return {"result": result, "win": bool(win), "mfe_pct": round(mfe, 2),
            "mae_pct": round(mae, 2), "r_multiple": r_mult}

def entry_from(after_klines, ds_entry):
    """Use the next candle OPEN at/after the anchor as the realistic fill, not the
    LLM's hoped entry (which may never have been touched)."""
    if after_klines:
        return after_klines[0]["o"]
    return ds_entry

def p(t): print("\n" + "=" * 78 + f"\n{t}\n" + "=" * 78)
def run(coro): return asyncio.run(coro)
