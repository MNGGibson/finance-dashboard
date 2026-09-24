import merchants as m

DESCRIPTIONS = [
    "AplPay CHICK-FIL-A #00808 0MARIETTA GA",
    "CHICK-FIL-A #00873 0ALPHARETTA GA",
    "WAL-MART SUPERCENTERMARIETTA GA",
    "WAL-MART SUPERCENTERALPHARETTA GA",
    "STARBUCKS 08371 0000SMYRNA GA",
    "STARBUCKS 26013 0000ALPHARETTA GA",
    "AMAZON MARKETPLACE NAMZN.COM/BILL WA",
    "SIRIUS XM RADIO INC.888-635-5144 NY",
    "PLAN FEE - AMAZON.COM",
    "Zelle: Zelle Payment to Someone",
    "PANDA EXPRESS DINE IN",
    "UBER EATS help.uber.com CA",
    "SAM'S CLUB 8203 8203MARIETTA GA",
    "WAFFLE HOUSE 0034 MARIETTA GA",
    "POPEYES 3121 MARIETTA GA",
    "RACETRAC PETROLEUM ALPHARETTA GA",
    "KROGER 0412 ALPHARETTA GA",
]
CITIES = m.learn_cities(DESCRIPTIONS)


def name(d):
    return m.merchant_name(d, CITIES)


def test_cities_are_learned_from_repeated_endings():
    assert {"MARIETTA", "ALPHARETTA"} <= CITIES
    assert "DINE" not in CITIES


def test_same_merchant_across_stores_and_wallets():
    assert name("AplPay CHICK-FIL-A #00808 0MARIETTA GA") == name("CHICK-FIL-A #00873 0ALPHARETTA GA")
    assert name("STARBUCKS 08371 0000SMYRNA GA") == name("STARBUCKS 26013 0000ALPHARETTA GA") == "Starbucks"


def test_glued_city_is_cut_at_the_merchant_field():
    assert name("WAL-MART SUPERCENTERMARIETTA GA") == "Walmart"


def test_aliases_and_special_cases():
    assert name("AMAZON MARKETPLACE NAMZN.COM/BILL WA") == "Amazon"
    assert name("SAM'S CLUB 8203 8203MARIETTA GA") == "Sam's Club"
    assert name("PLAN FEE - AMAZON.COM") == "Card plan fees"
    assert name("Zelle: Zelle Payment to Someone") == "Zelle to Someone"


def test_numbers_and_phone_numbers_are_dropped():
    assert name("SIRIUS XM RADIO INC.888-635-5144 NY") == "Sirius Xm"


def test_english_word_is_not_mistaken_for_a_state():
    assert name("PANDA EXPRESS DINE IN") == "Panda Express"
    assert name("SOME SHOP MARIETTA IN") == "Some Shop"  # a learned city before IN still counts


def test_add_merchants_adds_a_column():
    import pandas as pd
    df = pd.DataFrame({"description": DESCRIPTIONS[:2]})
    assert list(m.add_merchants(df, DESCRIPTIONS)["merchant"]) == ["Chick-Fil-A", "Chick-Fil-A"]
