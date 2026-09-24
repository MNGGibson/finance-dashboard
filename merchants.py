"""Turn raw bank descriptions into merchant names good enough to group spending by.

Card descriptions look like "AplPay CHICK-FIL-A #00808 0MARIETTA GA": a wallet or
processor prefix, the merchant, a store number, then city and state. Card networks cut
the merchant to a fixed width, so a long name often runs straight into the city with no
space ("WAL-MART SUPERCENTERMARIETTA GA"). Cities are learned from the descriptions
themselves, then a glued city is recognised as a suffix of the last word. This is a
heuristic, not a merchant database: it aims to put the same merchant in the same
bucket, and the dashboard says the grouping is approximate where it is shown.
"""

import re
from collections import Counter

MIN_CITY_SIGHTINGS = 2

STATES = set(
    "AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ "
    "NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY DC".split()
)
# State codes that are also English words ("DINE IN", "TO GO OR", "PAY ME"). These count as
# a state only when the word before them is a city already learned from unambiguous ones.
AMBIGUOUS_STATES = {"IN", "OR", "ME", "OK", "HI", "DE", "ID", "PA", "MA", "AL", "CO", "MT", "MD"}
# How you paid or how the bank labelled it, not where the money went.
PREFIXES = re.compile(r"^(APLPAY|GGLPAY|SQ \*|PAYPAL \*|DEBIT CARD:|ACH:|ZELLE:|DIRECT PAYMENT:|DIRECT DEPOSIT:)\s*")
PROCESSOR_CODE = re.compile(r"^[A-Z]{2,4}\*\s*")  # "TST*", "PAR*", "BT*", "TJ* "
CITY_FIRST_WORDS = {
    "NEW",
    "SAN",
    "LOS",
    "LAS",
    "SANTA",
    "FORT",
    "SAINT",
    "ST",
    "EL",
    "PORT",
    "CAPE",
    "MOUNTAIN",
    "HUNT",
    "NORTH",
    "SOUTH",
    "EAST",
    "WEST",
}
# The few brands big enough to show up under several spellings.
ALIASES = [
    (("AMAZON", "AMZN"), "Amazon"),
    (("WAL-MART", "WALMART", "WM SUPERCENTER"), "Walmart"),
    (("SAM'S CLUB", "SAMS CLUB", "SAMSCLUB"), "Sam's Club"),
]


def _words(description):
    return (description or "").upper().split()


def _glued_city(word, cities):
    """The learned city that `word` ends with, if the word is more than the city alone."""
    return next((c for c in sorted(cities, key=len, reverse=True) if word.endswith(c) and word != c), None)


def _ends_in_state(words, cities):
    if len(words) < 2 or words[-1] not in STATES:
        return False
    if words[-1] not in AMBIGUOUS_STATES:
        return True
    return words[-2] in cities or _glued_city(words[-2], cities) is not None


def learn_cities(descriptions):
    """Cities are whatever keeps showing up as the last word before an unambiguous state code."""
    sightings = Counter()
    for description in descriptions:
        words = _words(description)
        if _ends_in_state(words, frozenset()):
            city = words[-2]
            if city.isalpha() and len(city) >= 4:
                sightings[city] += 1
    cities = {city for city, n in sightings.items() if n >= MIN_CITY_SIGHTINGS}
    # A glued word that repeats ("SUPERCENTERMARIETTA") is a merchant tail plus a real city.
    return {c for c in cities if _glued_city(c, cities - {c}) is None}


def _strip_location(words, cities):
    """Words with the trailing city and state removed. Returns (words, had_location)."""
    if not _ends_in_state(words, cities):
        return words, False
    body = words[:-1]
    last = body[-1]
    glued = _glued_city(last, cities)
    # A plain word right before an unambiguous state code is a city even if it has been seen
    # only once ("CHICK-FIL-A #03717 0THOMSON GA"); learned cities are needed only for the
    # ambiguous codes and for a city glued onto the merchant.
    plain_city = words[-1] not in AMBIGUOUS_STATES and last.isalpha() and len(last) >= 3
    if last in cities or plain_city or re.fullmatch(r"\d+[A-Z]{3,}", last):  # "0NORCROSS"
        body = body[:-1]
    elif glued:
        body[-1] = last[: -len(glued)]
    if body and body[-1] in CITY_FIRST_WORDS:  # "SAN FRANCISCO": FRANCISCO was the learned word
        body = body[:-1]
    return body, True


def _strip_prefixes(text):
    while True:
        stripped = PROCESSOR_CODE.sub("", PREFIXES.sub("", text).strip()).strip()
        if stripped == text:
            return text
        text = stripped


def merchant_name(description, cities):
    words, _ = _strip_location(_words(description), cities)
    text = _strip_prefixes(" ".join(words))
    if text.startswith("PLAN FEE"):
        return "Card plan fees"
    if text.startswith("ZELLE PAYMENT TO "):
        return "Zelle to " + text[len("ZELLE PAYMENT TO ") :].title()
    for spellings, brand in ALIASES:
        if text.startswith(spellings):
            return brand

    words = text.replace("*", " ").split()
    # Store numbers, phone numbers and reference codes are not part of the name.
    words = [re.sub(r"^[\d\-]+", "", w.split("#")[0]) for w in words]  # "20121-CRUNCH" -> "CRUNCH"
    words = [w.strip("-.,&/") for w in words if not any(ch.isdigit() for ch in w)]
    words = [w for i, w in enumerate(words) if len(w) > 1 and (i == 0 or w != words[i - 1])]
    name = " ".join(words[:2]) or text
    return name.title().replace("'S", "'s")


def add_merchants(txns, all_descriptions):
    cities = learn_cities(all_descriptions)
    return txns.assign(merchant=[merchant_name(d, cities) for d in txns["description"]])
