"""Collect + compare all result_*_<seed>.json against the baseline. Run anytime."""
import sys, json, glob, os

seed = sys.argv[1] if len(sys.argv) > 1 else "42"
BASE = {"strategy": "BASELINE(prod)", "win_rate": 56.7, "dir_acc": "--",
        "expectancy_r": 0.307, "traded": 300, "abstained": 0,
        "short_n": 265, "short_wr": 57.0, "long_n": 35, "long_wr": 54.3}

files = sorted(glob.glob(f"result_*_{seed}.json"))
rows = [BASE]
for f in files:
    try:
        rows.append(json.load(open(f)))
    except Exception:
        pass

print(f"\n{'strategy':<22}{'win%':<7}{'dir%':<7}{'expR':<8}{'traded':<8}{'abst':<6}{'short(wr)':<14}{'long(wr)'}")
print("=" * 92)
for r in rows:
    sh = f"{r.get('short_n','?')}({r.get('short_wr','?')}%)"
    lo = f"{r.get('long_n','?')}({r.get('long_wr','?')}%)"
    print(f"{r.get('strategy','?'):<22}{str(r.get('win_rate')):<7}{str(r.get('dir_acc','--')):<7}"
          f"{str(r.get('expectancy_r')):<8}{str(r.get('traded')):<8}{str(r.get('abstained')):<6}{sh:<14}{lo}")
print(f"\n({len(files)} strategy result files found for seed {seed})")
