import classify


def test_merchant_key_prefers_the_bank_payee_and_strips_wallet_prefixes():
    assert classify.merchant_key("McDonald's", "AplPay MCDONALDS MARIETTA GA") == "mcdonald's"
    assert classify.merchant_key("Aplpay Fadeologist", "x") == "fadeologist"
    assert classify.merchant_key("", "WAL-MART SUPERCENTERMARIETTA GA", {"MARIETTA"}) == "walmart"
    assert classify.merchant_key(None, "CHICK-FIL-A #00808 0MARIETTA GA", {"MARIETTA"}) == "chick-fil-a"


def test_keywords_catch_the_obvious():
    assert classify.keyword_category("shell service station") == "spending:gas"
    assert classify.keyword_category("PLAN FEE - ROYAL CARIBBEA") == "bill:card_fees"
    assert classify.keyword_category("netflix.com") == "spending:subscriptions"
    assert classify.keyword_category("some unknown place") is None


def test_classifier_layers_and_learning():
    known = {"rico nail": "spending:personal_care"}
    c = classify.Classifier(known, ["RICO NAIL 000000001 SMYRNA GA"])
    assert c.category_for("Rico Nail", "RICO NAIL 000000001 SMYRNA GA") == "spending:personal_care"
    assert c.category_for("QuikTrip", "QT SMYRNA GA") == "spending:gas"  # keyword layer
    assert ("quiktrip", "spending:gas", "keyword") in c.learned
    assert c.category_for("Mystery Shop", "MYSTERY SHOP ATLANTA GA") is None
    assert c.pending == ["mystery shop"]
    assert c.resolve_pending(api_key=None) == {}  # no key: stays pending
    assert c.pending == ["mystery shop"]


def test_model_answers_are_validated(monkeypatch):
    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {
                                    "text": '{"Mystery Shop": "spending:shopping", "Nope": "spending:shopping", "Odd": "not-a-group"}'
                                }
                            ]
                        }
                    }
                ]
            }

    monkeypatch.setattr(classify.requests, "post", lambda *a, **k: FakeResponse())
    answers = classify.model_categories(["mystery shop", "odd"], api_key="k")
    assert answers == {"mystery shop": "spending:shopping"}
    assert classify.model_categories([], api_key="k") == {}
    assert classify.model_categories(["x"], api_key="") == {}


def test_money_coming_back_is_labelled_by_keyword():
    assert classify.keyword_category("AUTOPAY PAYMENT - THANK YOU") == classify.CARD_PAYMENT_RECEIVED
    assert classify.keyword_category("Platinum Walmart+ Credit") == classify.CARD_CREDIT
    assert classify.keyword_category("Interest earned") == classify.INTEREST
    assert classify.keyword_category("Zelle: Zelle Payment to Someone") == "spending:zelle_payments"
    assert classify.keyword_category("Debit Card: COSTCO *ANNUAL RENEWAL") == "spending:subscriptions"
    assert classify.keyword_category("COSTCO GAS #0631") == "spending:gas"


def test_bank_account_income_never_becomes_a_pending_merchant():
    c = classify.Classifier({}, [])
    assert c.category_for(None, "Zelle Payment from Someone", spending_only=False) is None
    assert c.pending == [] and c.learned == []


def test_fuel_in_the_raw_text_beats_the_payee_group():
    c = classify.Classifier({"sam's club": "spending:groceries"}, [])
    assert c.category_for("Sam's Club", "SAM'S CLUB FUEL 8203MARIETTA GA") == "spending:gas"
    assert c.category_for("Sam's Club", "SAM'S CLUB 8203 8203MARIETTA GA") == "spending:groceries"
    assert c.category_for("Walmart", "WALMART PHARMACY 1181") == "spending:health"
