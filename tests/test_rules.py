import pandas as pd
import pytest

import rules


def frame(rows):
    """rows: (posted, amount, category, account_type)."""
    df = pd.DataFrame(rows, columns=["posted", "amount", "category", "account_type"])
    df["posted"] = pd.to_datetime(df["posted"])
    df["account_id"] = df["account_type"]
    return df


@pytest.fixture
def month():
    return frame(
        [
            ("2026-09-02", 2000.0, "income:paycheck", "checking"),
            ("2026-09-03", -1500.0, "bill:rent", "checking"),
            ("2026-09-05", -300.0, "spending:discretionary", "credit_card"),
            ("2026-09-06", -100.0, "spending:discretionary", "credit_card"),
            ("2026-09-08", -400.0, "bill:debt_payment", "checking"),  # paying the card
            ("2026-09-08", 400.0, None, "credit_card"),  # payment received on the card
            ("2026-09-12", 250.0, "transfer:points_redemption", "credit_card"),
            ("2026-09-12", -250.0, "transfer:points_redemption", "credit_card"),
        ]
    )


def test_income_excludes_card_credits_and_transfers(month):
    assert month.loc[rules.income_mask(month), "amount"].sum() == 2000.0


def test_card_payments_are_not_bills(month):
    income, bills, spending = rules.month_totals(month)
    assert (income, bills, spending) == (2000.0, 1500.0, 400.0)
    assert income - bills - spending == 100.0  # the "left for debt and savings" tile


def test_rent_in_the_last_three_days_counts_for_next_month():
    df = frame(
        [
            ("2026-08-28", -1500.0, "bill:rent", "checking"),  # 4th-last day: stays
            ("2026-08-30", -1500.0, "bill:rent", "checking"),  # moves to September
            ("2026-08-31", -1500.0, "bill:rent", "checking"),  # moves to September
            ("2026-08-31", -50.0, "spending:discretionary", "credit_card"),  # not rent: stays
        ]
    )
    months = rules.effective_date(df).dt.to_period("M").astype(str).tolist()
    assert months == ["2026-08", "2026-09", "2026-09", "2026-08"]


def test_category_label():
    assert rules.category_label("bill:debt_payment") == "Debt payment"
    assert rules.category_label(None) == "Uncategorized"
    assert rules.category_label("odd") == "Uncategorized"


def test_days_counted():
    today = pd.Timestamp("2026-09-17")
    assert rules.days_counted(pd.Period("2026-09", "M"), today) == 17
    assert rules.days_counted(pd.Period("2026-08", "M"), today) == 31


def test_net_worth_as_of_uses_one_sync_run():
    history = pd.DataFrame(
        {
            "as_of": pd.to_datetime(["2026-07-21", "2026-07-21", "2026-09-10", "2026-09-10"]),
            "balance": [100.0, -50.0, 120.0, -40.0],
            "account_id": ["a", "b", "a", "b"],
        }
    )
    total, run = rules.net_worth_as_of(history, pd.Timestamp("2026-09-01"))
    assert (total, run) == (50.0, pd.Timestamp("2026-07-21"))
    assert rules.net_worth_as_of(history, pd.Timestamp("2026-01-01")) == (None, None)


def test_rank_by_folds_the_tail():
    df = pd.DataFrame({"merchant": list("aaabbcdef"), "amount": [-1.0] * 9})
    ranked = rules.rank_by(df, "merchant", keep=2)
    assert list(ranked["label"]) == ["a", "b", "4 others"]
    assert list(ranked["amount"]) == [3.0, 2.0, 4.0]
    assert list(ranked["is_rest"]) == [False, False, True]


def test_date_range_presets():
    today = pd.Timestamp("2026-09-26")
    assert rules.date_range_for("This month", today) == (pd.Timestamp("2026-09-01"), today)
    assert rules.date_range_for("Last month", today) == (pd.Timestamp("2026-08-01"), pd.Timestamp("2026-08-31"))
    assert rules.date_range_for("Last 3 months", today) == (pd.Timestamp("2026-07-01"), today)
    assert rules.date_range_for("Year to date", today) == (pd.Timestamp("2026-01-01"), today)
    assert rules.date_range_for("Custom", today, ("2026-09-10", "2026-09-03")) == (
        pd.Timestamp("2026-09-03"),
        pd.Timestamp("2026-09-10"),
    )
    assert rules.date_range_for("Custom", today, None) == (pd.Timestamp("2026-09-01"), today)


def test_previous_range_is_like_for_like_for_the_current_month():
    today = pd.Timestamp("2026-09-26")
    assert rules.previous_range(pd.Timestamp("2026-09-01"), today, today) == (
        pd.Timestamp("2026-08-01"),
        pd.Timestamp("2026-08-26"),
    )
    # a whole past month compares with the whole month before it
    assert rules.previous_range(pd.Timestamp("2026-08-01"), pd.Timestamp("2026-08-31"), today) == (
        pd.Timestamp("2026-07-01"),
        pd.Timestamp("2026-07-31"),
    )


def test_monthly_totals_zero_fills():
    df = frame(
        [
            ("2026-09-02", 2000.0, "income:paycheck", "checking"),
            ("2026-07-05", -300.0, "spending:discretionary", "credit_card"),
        ]
    )
    df["effective"] = df["posted"]
    df["month"] = df["effective"].dt.to_period("M")
    out = rules.monthly_totals(df, pd.Period("2026-09", "M"), months=3)
    assert [str(m) for m in out["month"]] == ["2026-07", "2026-08", "2026-09"]
    assert list(out["spending"]) == [300.0, 0.0, 0.0]
    assert list(out["left_over"]) == [-300.0, 0.0, 2000.0]


def test_describe_range():
    assert rules.describe_range(pd.Timestamp("2026-09-01"), pd.Timestamp("2026-09-26")) == "Sep 1–26, 2026"
    assert rules.describe_range(pd.Timestamp("2026-07-01"), pd.Timestamp("2026-09-26")) == "Jul 1 – Sep 26, 2026"


def test_year_to_date_compares_with_last_year():
    today = pd.Timestamp("2026-09-26")
    assert rules.previous_range(pd.Timestamp("2026-01-01"), today, today) == (
        pd.Timestamp("2025-01-01"),
        pd.Timestamp("2025-09-26"),
    )
