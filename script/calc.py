"""Compound-interest table: $100 at the end of each month, 7% annual, monthly compounding."""
import json
import sys

MONTHLY = 100
RATE = 0.07
YEARS = int(sys.argv[1]) if len(sys.argv) > 1 else 30

r = RATE / 12
balance = 0.0
rows = []
crossover = None
for m in range(1, YEARS * 12 + 1):
    balance = balance * (1 + r) + MONTHLY
    contributed = m * MONTHLY
    if crossover is None and balance - contributed > contributed:
        crossover = m
    if m % 12 == 0:
        rows.append({"year": m // 12, "contributed": contributed,
                     "balance": round(balance, 2), "interest": round(balance - contributed, 2)})

print(json.dumps({"monthly": MONTHLY, "rate": RATE, "crossoverMonth": crossover, "years": rows},
                 ensure_ascii=False, indent=1))
