"""Run several strategies back-to-back (reusing the cached dataset) and print a
comparison table. Use after the dataset cache exists.

Usage: python run_ladder.py 150 42  rich_features reversal_guard regime_gated bull_bear_debate
"""
import sys, asyncio, json
sys.path.insert(0, ".")
from p4_engine import run_strategy

async def main(n, seed, names):
    rows = []
    for name in names:
        r = await run_strategy(name, n, seed)
        rows.append(r)
    print("\n" + "=" * 90)
    print(f"{'strategy':<22}{'win%':<7}{'dir%':<7}{'exp_R':<8}{'traded':<8}{'abst':<6}{'short(wr)':<14}{'long(wr)'}")
    print("=" * 90)
    print(f"{'BASELINE(prod signals)':<22}{'56.7':<7}{'--':<7}{'+0.307':<8}{'300':<8}{'0':<6}{'265(57%)':<14}{'35(54%)'}")
    for r in rows:
        short_s = f"{r['short_n']}({r['short_wr']:.0f}%)"
        long_s = f"{r['long_n']}({r['long_wr']:.0f}%)"
        print(f"{r['strategy']:<22}{r['win_rate']:<7}{str(r.get('dir_acc','--')):<7}"
              f"{r['expectancy_r']:<+8}{r['traded']:<8}{r['abstained']:<6}{short_s:<14}{long_s}")

if __name__ == "__main__":
    n = int(sys.argv[1]); seed = int(sys.argv[2]); names = sys.argv[3:]
    asyncio.run(main(n, seed, names))
