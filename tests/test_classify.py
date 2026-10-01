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
        status_code = 200

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


def test_review_applies_only_valid_changes(monkeypatch):
    class FakeResponse:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return {
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {
                                    "text": '[{"id": "a", "category": "spending:gas", "reason": "fuel pump"},'
                                    ' {"id": "b", "category": "spending:groceries", "reason": "same as proposed"},'
                                    ' {"id": "c", "category": "made-up", "reason": "x"},'
                                    ' {"id": "zzz", "category": "spending:gas", "reason": "unknown id"}]'
                                }
                            ]
                        }
                    }
                ]
            }

    monkeypatch.setattr(classify.requests, "post", lambda *a, **k: FakeResponse())
    items = [
        {
            "id": "a",
            "description": "SAM'S CLUB FUEL 8203",
            "payee": "Sam's Club",
            "amount": -40.0,
            "account_type": "credit_card",
            "proposed": "spending:groceries",
        },
        {
            "id": "b",
            "description": "SAM'S CLUB 8203",
            "payee": "Sam's Club",
            "amount": -90.0,
            "account_type": "credit_card",
            "proposed": "spending:groceries",
        },
        {
            "id": "c",
            "description": "X",
            "payee": "",
            "amount": -1.0,
            "account_type": "credit_card",
            "proposed": "spending:other",
        },
    ]
    assert classify.review_categories(items, api_key="k") == {"a": ("spending:gas", "fuel pump")}
    assert classify.review_categories(items, api_key="") == {}
    assert classify.review_categories([], api_key="k") == {}


def test_review_cleans_numbers_out_of_the_text():
    assert classify._clean_for_review("CHICK-FIL-A #00808 0MARIETTA GA") == "CHICK-FIL-A 0MARIETTA GA"
    assert classify._clean_for_review("SIRIUS XM RADIO INC.888-635-5144 NY") == "SIRIUS XM RADIO INC. NY"


def test_fees_and_memberships_beat_the_issuing_stores_group():
    c = classify.Classifier({"amazon": "spending:shopping", "walmart": "spending:groceries"}, [])
    assert c.category_for("Amazon", "PLAN FEE - AMAZON.COM") == "bill:card_fees"
    assert c.category_for("Amazon", "AMAZON PRIME*E334C8Z AMZN.COM") == "spending:subscriptions"
    assert c.category_for("Walmart", "Walmart+ Member 07/28") == "spending:subscriptions"
    assert c.category_for("Sam's Club", "SAMS CLUB RENEWAL MORROW GA") == "spending:subscriptions"
    assert c.category_for("Amazon", "AMAZON MARKETPLACE NAMZN.COM") == "spending:shopping"


def test_credit_wording():
    assert classify.credit_wording("Platinum Walmart+ Credit")
    assert classify.credit_wording("AMEX Airline Fee Reimbursement")
    assert not classify.credit_wording("OURARING SAN FRANCISCO CA")


def test_model_changes_are_limited_by_sign_and_account():
    def item(amount, kind, proposed, description="X"):
        return {"amount": amount, "account_type": kind, "proposed": proposed, "description": description}

    # a charge cannot become a credit or income
    assert not classify.change_is_sane(item(-20, "credit_card", "spending:shopping"), classify.CARD_CREDIT)
    assert not classify.change_is_sane(item(-20, "checking", "spending:other"), "income:other")
    assert classify.change_is_sane(item(-20, "credit_card", "spending:groceries"), "spending:gas")
    # money into a bank account is never spending or a bill
    assert not classify.change_is_sane(item(138, "checking", "income:other"), "spending:zelle_payments")
    assert classify.change_is_sane(item(138, "checking", "spending:other"), "income:other")
    # a refund of a purchase keeps its group unless the text says credit/payment
    assert not classify.change_is_sane(item(264, "credit_card", "spending:shopping", "OURARING"), classify.CARD_CREDIT)
    assert classify.change_is_sane(
        item(75, "credit_card", "spending:shopping", "Platinum Lululemon Credit"), classify.CARD_CREDIT
    )
    assert classify.change_is_sane(
        item(20, "credit_card", "spending:shopping", "AUTOPAY PAYMENT"), classify.CARD_PAYMENT_RECEIVED
    )


def test_memory_never_assigns_a_group_to_money_arriving_in_a_bank_account():
    # Zelle uses one generic payee in both directions; a remembered outgoing payment must not claim a deposit.
    c = classify.Classifier({"zelle transfer": "spending:zelle_payments"}, [])
    assert c.category_for("Zelle Transfer", "Zelle Payment from Someone", spending_only=False) is None
    assert c.category_for("Zelle Transfer", "Zelle: Zelle Payment to Someone") == "spending:zelle_payments"


def test_row_specific_text_is_used_but_never_remembered():
    c = classify.Classifier({}, [])
    assert c.category_for("Zelle Transfer", "Zelle: Zelle Payment to Someone") == "spending:zelle_payments"
    assert c.learned == [] and "zelle transfer" not in c.known
