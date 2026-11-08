"""Compound interest: $100 deposited at the end of every month, 7% annual, compounded monthly.

python3 script/calc.py            -> prints the yearly table
python3 script/calc.py --json F   -> also writes all numbers the video uses to F
"""
import json
import sys

MONTHLY = 100
RATE = 0.07
YEARS = 30
r = RATE / 12


def balances(months):
    out, b = [0.0], 0.0
    for _ in range(months):
        b = b * (1 + r) + MONTHLY
        out.append(b)
    return out


bal = balances(YEARS * 12)
crossover = next(m for m in range(1, len(bal)) if bal[m] - m * MONTHLY > m * MONTHLY)


def year_row(y):
    m = y * 12
    return {"year": y, "contributed": m * MONTHLY, "balance": round(bal[m], 2),
            "interest": round(bal[m] - m * MONTHLY, 2),
            "interestThisYear": round(bal[m] - bal[m - 12] - 12 * MONTHLY, 2) if y else 0}


# monthly deposit needed to reach the 20-year result in only 10 years (start later)
target = bal[240]
need_10y = target * r / ((1 + r) ** 120 - 1)

data = {
    "monthly": MONTHLY, "rate": RATE, "crossoverMonth": crossover,
    "months": [round(x, 2) for x in bal],
    "years": [year_row(y) for y in range(YEARS + 1)],
    "needMonthlyFor10y": round(need_10y, 2),
    "perDay": round(MONTHLY * 12 / 365, 2),
}

if __name__ == "__main__":
    for row in data["years"]:
        print(f'{row["year"]:>2}  вложено {row["contributed"]:>7,.0f}  на счёте {row["balance"]:>10,.0f}  '
              f'доход {row["interest"]:>9,.0f}  доход за год {row["interestThisYear"]:>7,.0f}')
    print("доход > вложений с месяца", crossover, f"({crossover / 12:.2f} лет)")
    print("нужно в месяц, чтобы получить ту же сумму за 10 лет:", round(need_10y, 2))
    if "--json" in sys.argv:
        with open(sys.argv[sys.argv.index("--json") + 1], "w") as f:
            json.dump(data, f, ensure_ascii=False)
