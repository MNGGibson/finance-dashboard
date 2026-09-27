"""Sort card spending into groups by merchant.

Three layers, cheapest first. A category set by hand (scripts/classify.py --set) always
wins. Then a keyword list catches the obvious names with no model call. Then, when a
GEMINI_API_KEY is configured, Google's free-tier model classifies whatever is left, and
the answer is saved so every merchant is classified once. Nothing here sees amounts,
accounts or dates: only the merchant name goes out.
"""

import json
import re

import requests

from merchants import learn_cities, merchant_name

# The groups. Keys are stored categories; values describe them for the model and the docs.
GROUPS = {
    "spending:groceries": "supermarkets, warehouse clubs, farmers markets, meal kits, convenience stores",
    "spending:fast_food": "fast food, quick service, coffee, ice cream, vending, snacks",
    "spending:dining": "sit-down restaurants, bars, cafes, food delivery",
    "spending:gas": "gas stations and fuel",
    "spending:shopping": "retail, online shopping, clothing, home goods, gifts, flowers",
    "spending:subscriptions": "streaming, software, memberships, online services billed monthly",
    "spending:health": "pharmacies, doctors, medical, health products",
    "spending:personal_care": "barbers, salons, nails, beauty supply, laundry",
    "spending:fitness": "gyms and fitness",
    "spending:education": "courses, certifications, tuition, school fees",
    "spending:travel": "airlines, hotels, cruises, travel agencies, resorts, airport shops",
    "spending:entertainment": "cinemas, parks, events, games, attractions",
    "spending:transport": "rideshare, tolls, parking, car service, car wash, DMV, moving trucks",
    "spending:zelle_payments": "money sent to people through Zelle, Venmo or Cash App",
    "bill:utilities": "internet, phone, electricity, water",
    "bill:card_fees": "card interest, late fees, plan fees, convenience fees",
    "spending:other": "anything that fits none of the above",
}
# Labels for money coming back, not spending: decided by keyword, never by the model.
CARD_PAYMENT_RECEIVED = "transfer:card_payment"  # your own payment landing on the card
CARD_CREDIT = "refund:card_credit"  # statement credits and perks
INTEREST = "income:interest"

# Obvious names: matched as case-insensitive substrings of the merchant name, first hit wins.
KEYWORDS = [
    (("payment - thank you", "autopay payment", "mobile payment"), CARD_PAYMENT_RECEIVED),
    (
        (
            "statement credit",
            "fee reimbursement",
            "platinum walmart+ credit",
            "platinum resy credit",
            "platinum digital entertainment credit",
            "platinum lululemon credit",
            " credit",
        ),
        CARD_CREDIT,
    ),
    (("interest earned",), INTEREST),
    (("plan fee", "late fee", "interest charge", "convenience fee", "annual fee"), "bill:card_fees"),
    (("zelle payment to", "zelle transfer to", "venmo", "cash app"), "spending:zelle_payments"),
    (("rp resident", "resident dire"), "bill:rent"),
    (("costco gas", "kroger fuel", "walmart fuel", "sam's club fuel"), "spending:gas"),
    (("annual renewal", "membership fee", "membership renewal"), "spending:subscriptions"),
    (("klarna", "affirm", "afterpay"), "spending:shopping"),
    (("comcast", "xfinity", "at&t", "verizon", "t-mobile", "georgia power", "spectrum"), "bill:utilities"),
    (
        (
            "fuel",
            "shell",
            "chevron",
            "exxon",
            "quiktrip",
            "racetrac",
            "marathon",
            "murphy usa",
            "citgo",
            "bp gas",
            "bp#",
            "texaco",
            "sunoco",
            "wawa",
            "7-eleven",
        ),
        "spending:gas",
    ),
    (
        (
            "kroger",
            "publix",
            "aldi",
            "walmart",
            "wal-mart",
            "sam's club",
            "costco",
            "whole foods",
            "trader joe",
            "food mart",
            "farmers market",
            "hellofresh",
            "market",
        ),
        "spending:groceries",
    ),
    (
        (
            "netflix",
            "disney+",
            "disney plus",
            "hulu",
            "spotify",
            "sirius",
            "xbox",
            "playstation",
            "microsoft 365",
            "openai",
            "chatgpt",
            "claude",
            "anthropic",
            "amazon prime",
            "linkedin",
            "prime membership",
            "subscription",
            "simplefin",
        ),
        "spending:subscriptions",
    ),
    (
        (
            "mcdonald",
            "chick-fil-a",
            "popeyes",
            "wendy",
            "burger king",
            "kfc",
            "taco bell",
            "zaxby",
            "bojangles",
            "whataburger",
            "raising cane",
            "cook out",
            "steak 'n shake",
            "chipotle",
            "moe's",
            "firehouse",
            "subway",
            "panda express",
            "panera",
            "starbucks",
            "dunkin",
            "krispy kreme",
            "dairy queen",
            "cold stone",
            "smoothie king",
            "waffle house",
            "coca cola",
            "nayax",
            "vending",
            "chicken salad chick",
            "sliders",
            "jersey mike",
            "sonic",
            "arby",
            "cava",
        ),
        "spending:fast_food",
    ),
    (
        (
            "uber eats",
            "doordash",
            "grubhub",
            "restaurant",
            "grill",
            "cantina",
            "taqueria",
            "cafe",
            "bar &",
            "sports bar",
            "buffet",
            "kitchen",
            "roadhouse",
            "cracker barrel",
            "chili's",
            "ihop",
            "olive garden",
            "cheddar",
            "yard house",
            "bakery",
            "pizza",
            "papa john",
            "hibachi",
            "sushi",
            "bistro",
            "diner",
            "eatery",
        ),
        "spending:dining",
    ),
    (("crunch fitness", "fitness", "gym", "planet fitness", "la fitness", "ymca"), "spending:fitness"),
    (
        (
            "cinema",
            "theater",
            "theatre",
            "amc ",
            "regal",
            "water park",
            "six flags",
            "motorsports",
            "bowling",
            "arcade",
            "museum",
            "zoo",
            "ticketmaster",
        ),
        "spending:entertainment",
    ),
    (
        (
            "delta air",
            "united air",
            "american air",
            "southwest",
            "airline",
            "hotel",
            "inn ",
            "marriott",
            "hilton",
            "hyatt",
            "airbnb",
            "cruise",
            "royal caribbean",
            "travel",
            "resort",
            "airport",
        ),
        "spending:travel",
    ),
    (
        (
            "uber",
            "lyft",
            "toll",
            "parking",
            "mvd",
            "dmv",
            "car wash",
            "wash depot",
            "u-haul",
            "toyota",
            "honda",
            "jiffy lube",
            "tire",
        ),
        "spending:transport",
    ),
    (("walgreens", "cvs", "pharmacy", "hims & hers", "dental", "clinic", "medical", "urgent care"), "spending:health"),
    (("barber", "fadeologist", "salon", "nail", "beauty", "laundry", "laundromat", "spa "), "spending:personal_care"),
    (
        ("coursera", "udemy", "measureup", "parchment", "university", "college", "tuition", "upskill"),
        "spending:education",
    ),
    (
        (
            "amazon",
            "target",
            "best buy",
            "home depot",
            "lowe's",
            "dollar tree",
            "family dollar",
            "five below",
            "ross",
            "burlington",
            "tj maxx",
            "marshalls",
            "lululemon",
            "nike",
            "shoes",
            "dick's",
            "ollie",
            "tiktok shop",
            "etsy",
            "ebay",
            "goat",
            "flowers",
            "bouqs",
            "cosmoflora",
        ),
        "spending:shopping",
    ),
]

DEFAULT = "spending:discretionary"  # unclassified card spending, until a layer above catches it
MODEL = "gemini-2.5-flash-lite"


def merchant_key(payee, description, cities=frozenset()):
    """The name a merchant is stored under: the bank's cleaned payee when it gives one,
    otherwise the name recovered from the raw description. Lower-cased, wallet prefixes gone."""
    name = (payee or "").strip()
    if not name:
        name = merchant_name(description, cities)
    name = re.sub(r"^(aplpay|gglpay|apple pay|google pay)\s+", "", name, flags=re.I).strip()
    return re.sub(r"\s+", " ", name).lower()


def keyword_category(name):
    lowered = name.lower()
    for needles, category in KEYWORDS:
        if any(needle in lowered for needle in needles):
            return category
    return None


def model_categories(names, api_key, model=MODEL, timeout=60):
    """Ask Gemini to place each name into one of GROUPS. Returns {name: category} for the
    names it answered validly; anything else is simply absent. Raises on a transport error."""
    names = [n for n in dict.fromkeys(names) if n]
    if not names or not api_key:
        return {}
    groups = "\n".join(f"- {key}: {what}" for key, what in GROUPS.items())
    prompt = (
        "Classify each merchant name from a US credit card statement into exactly one group. "
        "Answer with a JSON object mapping each name to a group key.\n\nGroups:\n"
        f"{groups}\n\nMerchants:\n" + "\n".join(f"- {n}" for n in names)
    )
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"responseMimeType": "application/json", "temperature": 0},
    }
    response = requests.post(url, params={"key": api_key}, json=body, timeout=timeout)
    response.raise_for_status()
    text = response.json()["candidates"][0]["content"]["parts"][0]["text"]
    answers = json.loads(text)
    wanted = {n.lower(): n for n in names}
    result = {}
    for raw_name, category in answers.items():
        name = wanted.get(str(raw_name).strip().lower())
        if name and category in GROUPS:
            result[name] = category
    return result


class Classifier:
    """Resolves a merchant's category through the layers, remembering what it learns.

    `known` is the merchant_categories table as {merchant: category}. New answers from the
    keyword layer are recorded in `learned` (as (merchant, category, source)) for the caller
    to persist; names nothing could place are collected in `pending` for the model layer.
    """

    def __init__(self, known, descriptions=()):
        self.known = dict(known)
        self.cities = learn_cities(descriptions)
        self.learned = []
        self.pending = []

    def category_for(self, payee, description, spending_only=True):
        """The group for a merchant, or None. With spending_only=False (money arriving in a
        bank account) only the keyword layer applies: no merchant is learned or sent out."""
        name = merchant_key(payee, description, self.cities)
        if name in self.known:
            return self.known[name]
        category = keyword_category(name) or keyword_category(description or "")
        if category:
            if spending_only:
                self.known[name] = category
                self.learned.append((name, category, "keyword"))
            return category
        if spending_only and name not in self.pending:
            self.pending.append(name)
        return None

    def resolve_pending(self, api_key):
        """Classify the pending names with the model, if a key is configured."""
        if not api_key or not self.pending:
            return {}
        answers = model_categories(self.pending, api_key)
        for name, category in answers.items():
            self.known[name] = category
            self.learned.append((name, category, "model"))
        self.pending = [n for n in self.pending if n not in answers]
        return answers
