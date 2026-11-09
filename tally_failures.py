import json
from collections import Counter

with open("data/faithful_btc_1y_traceability_audit.json") as f:
    data = json.load(f)

evals = data.get("evaluations", [])
c = Counter()
for e in evals:
    if not e.get("is_executed"):
        c[e.get("rejection_reason")] += 1

print(f"Total evaluated setups: {len(evals)}")
print("\nRejection reasons breakdown:")
for reason, count in c.most_common():
    print(f"  [{count} setups] {reason}")
