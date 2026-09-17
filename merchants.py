"""Turn raw bank descriptions into merchant names good enough to group spending by.

Card descriptions look like "AplPay CHICK-FIL-A #00808 0MARIETTA GA": a wallet or
processor prefix, the merchant, a store number, then city and state. Card networks pad
or cut the merchant to 20 characters, so a long name runs straight into the city with
no space ("WAL-MART SUPERCENTERMARIETTA GA"). This is a heuristic, not a merchant
database: it aims to put the same merchant in the same bucket, and the dashboard says
the grouping is approximate where it is shown.
"""
import re
from collections import Counter

MERCHANT_FIELD_WIDTH = 20
MIN_CITY_SIGHTINGS = 2

STATES = set(
    "AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ "
    "NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY DC".split()
)
# How you paid or how the bank labelled it, not where the money went.
PREFIXES = re.compile(
    r"^(APLPAY|GGLPAY|SQ \*|PAYPAL \*|DEBIT CARD:|ACH:|ZELLE:|DIRECT PAYMENT:|DIRECT DEPOSIT:)\s*")
PROCESSOR_CODE = re.compile(r"^[A-Z]{2,4}\*\s*")  # "TST*", "PAR*", "BT*", "TJ* "
CITY_FIRST_WORDS = {"NEW", "SAN", "LOS", "LAS", "SANTA", "FORT", "SAINT", "ST", "EL", "PORT", "CAPE",
                    "MOUNTAIN", "HUNT", "NORTH", "SOUTH", "EAST", "WEST"}
# The few brands big enough to show up under several spellings.
ALIASES = [(("AMAZON", "AMZN"), "Amazon"), (("WAL-MART", "WALMART", "WM SUPERCENTER"), "Walmart"),
           (("SAM'S CLUB", "SAMS CLUB", "SAMSCLUB"), "Sam's Club")]


def _split_location(description):
    """(text without city/state, had_state). Cuts a glued city off at the 20-char merchant field."""
    text = (description or "").upper().strip()
    words = text.split()
    if len(words) < 2 or words[-1] not in STATES:
        return text, False
    glued = (len(text) > MERCHANT_FIELD_WIDTH
             and text[MERCHANT_FIELD_WIDTH - 1] != " " and text[MERCHANT_FIELD_WIDTH] != " ")
    if glued:
        return text[:MERCHANT_FIELD_WIDTH], False  # city already removed with the cut
    return " ".join(words[:-1]), True


def _strip_prefixes(text):
    while True:
        stripped = PROCESSOR_CODE.sub("", PREFIXES.sub("", text).strip()).strip()
        if stripped == text:
            return text
        text = stripped


def learn_cities(descriptions):
    """Cities are whatever keeps showing up as the last word before a state code."""
    sightings = Counter()
    for description in descriptions:
        text, has_city = _split_location(description)
        last = text.split()[-1:] if has_city else []
        if last and last[0].isalpha() and len(last[0]) >= 4:
            sightings[last[0]] += 1
    return {city for city, n in sightings.items() if n >= MIN_CITY_SIGHTINGS}


def merchant_name(description, cities):
    text, has_city = _split_location(description)
    text = _strip_prefixes(text)
    if text.startswith("PLAN FEE"):
        return "Card plan fees"
    if text.startswith("ZELLE PAYMENT TO "):
        return "Zelle to " + text[len("ZELLE PAYMENT TO "):].title()
    for spellings, brand in ALIASES:
        if text.startswith(spellings):
            return brand

    words = text.replace("*", " ").split()
    if has_city and words and words[-1] in cities:
        words = words[:-1]
        if words and words[-1] in CITY_FIRST_WORDS:
            words = words[:-1]
    # Store numbers, phone numbers and reference codes are not part of the name.
    words = [re.sub(r"^[\d\-]+", "", w.split("#")[0]) for w in words]  # "20121-CRUNCH" -> "CRUNCH"
    words = [w.strip("-.,&/") for w in words if not any(ch.isdigit() for ch in w)]
    words = [w for i, w in enumerate(words) if len(w) > 1 and (i == 0 or w != words[i - 1])]
    name = " ".join(words[:2]) or text
    return name.title().replace("'S", "'s")


def add_merchants(txns, all_descriptions):
    cities = learn_cities(all_descriptions)
    return txns.assign(merchant=[merchant_name(d, cities) for d in txns["description"]])
