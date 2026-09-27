import importlib
import os
import sys
from pathlib import Path

os.environ.setdefault("SIMPLEFIN_ACCESS_URL", "https://user:pass@example.invalid/simplefin")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
sync = importlib.import_module("sync")
import classify  # noqa: E402


def test_capped_window_is_only_a_notice(capsys):
    data = {"errors": ["Requested date range exceeds limit of 90 days and was capped."], "accounts": [{"id": "a"}]}
    assert sync.response_problems(data) is False
    assert "notice" in capsys.readouterr().out


def test_real_errors_and_empty_responses_fail(capsys):
    assert sync.response_problems({"errors": ["Connection needs re-authorization"], "accounts": [{"id": "a"}]}) is True
    assert sync.response_problems({"errors": [], "accounts": []}) is True
    assert "re-authorization" in capsys.readouterr().err


def test_categorize_rules_then_card_fallback():
    rules = [("acme corp", "income:paycheck"), ("amex epayment", "bill:debt_payment")]
    assert sync.categorize("ACH: ACME CORP PAYROLL", rules) == "income:paycheck"
    assert (
        sync.categorize("STARBUCKS 08371", rules, account_type="credit_card", amount=-5.0) == "spending:discretionary"
    )
    assert sync.categorize("Refund", rules, account_type="credit_card", amount=5.0) is None
    assert sync.categorize("STARBUCKS", rules, account_type=None, amount=-5.0) is None


def test_categorize_routes_card_credits_and_bank_debits():
    c = classify.Classifier({"amazon": "spending:shopping"}, [])
    assert (
        sync.categorize("AMAZON MARKETPLACE", [], "credit_card", 50.0, c, "Amazon") == "spending:shopping"
    )  # refund nets
    assert (
        sync.categorize("AUTOPAY PAYMENT - THANK YOU", [], "credit_card", 20.0, c, None)
        == classify.CARD_PAYMENT_RECEIVED
    )
    assert sync.categorize("Platinum Resy Credit", [], "credit_card", 100.0, c, None) == classify.CARD_CREDIT
    assert (
        sync.categorize("Zelle: Zelle Payment to Someone", [], "checking", -50.0, c, None) == "spending:zelle_payments"
    )
    assert sync.categorize("Interest earned", [], "checking", 1.5, c, None) == classify.INTEREST
    assert sync.categorize("MYSTERY", [], "checking", -9.0, c, None) == classify.DEFAULT
    assert sync.categorize("Zelle Payment from Someone", [], "checking", 25.0, c, None) == "income:other"
