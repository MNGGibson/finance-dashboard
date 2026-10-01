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

# Words in the raw bank text that override the merchant's usual group: a warehouse club's
# fuel pump is gas even though the bank names the payee "Sam's Club".
DESCRIPTION_OVERRIDES = [
    (("fuel", "gas station", "gas #", "gasoline"), "spending:gas"),
    (("pharmacy",), "spending:health"),
    # Fees and memberships hide behind the payee of the store that issued them ("Amazon", "Walmart").
    (("plan fee", "renewal membership fee", "late fee", "interest charge"), "bill:card_fees"),
    (("amazon prime", "walmart+", "club renewal", "annual renewal"), "spending:subscriptions"),
]


def credit_wording(description):
    """True for text that says a credit-card credit is a perk, reimbursement or statement credit."""
    return bool(re.search(r"\b(credit|reimburse\w*|perk)\b", (description or "").lower()))


DEFAULT = "spending:discretionary"  # unclassified card spending, until a layer above catches it
MODEL = "gemini-flash-lite-latest"  # an alias Google keeps pointing at the current free Flash-Lite model
# Tried in turn when a model answers 503 "high demand", which the free tier does now and then.
MODEL_FALLBACKS = (MODEL, "gemini-3.1-flash-lite", "gemini-2.5-flash-lite", "gemini-flash-latest")


def _generate(prompt, api_key, model, timeout):
    """One JSON answer from the first model in the fallback list that is not overloaded."""
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"responseMimeType": "application/json", "temperature": 0},
    }
    models = [model] + [m for m in MODEL_FALLBACKS if m != model]
    last_error = None
    for candidate in models:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{candidate}:generateContent"
        # The key travels in a header, never in the URL, so it cannot appear in error messages or logs.
        response = requests.post(url, headers={"x-goog-api-key": api_key}, json=body, timeout=timeout)
        if response.status_code in (503, 429, 404):
            last_error = requests.HTTPError(f"{response.status_code} from {candidate}", response=response)
            continue
        response.raise_for_status()
        return json.loads(response.json()["candidates"][0]["content"]["parts"][0]["text"])
    raise last_error


def merchant_key(payee, description, cities=frozenset()):
    """The name a merchant is stored under: the bank's cleaned payee when it gives one,
    otherwise the name recovered from the raw description. Lower-cased, wallet prefixes gone."""
    name = (payee or "").strip()
    if not name:
        name = merchant_name(description, cities)
    name = re.sub(r"^(aplpay|gglpay|apple pay|google pay)\s+", "", name, flags=re.I).strip()
    return re.sub(r"\s+", " ", name).lower()


def description_override(description):
    lowered = (description or "").lower()
    for needles, category in DESCRIPTION_OVERRIDES:
        if any(needle in lowered for needle in needles):
            return category
    return None


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
    answers = _generate(prompt, api_key, model, timeout)
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
        override = description_override(description)
        if override:
            return override
        name = merchant_key(payee, description, self.cities)
        # Memory is only consulted for money going out. A bank labels both directions of a Zelle
        # payment with the same generic payee, so remembered spending must never claim a deposit.
        if spending_only and name in self.known:
            return self.known[name]
        category = keyword_category(name)
        if category:
            if spending_only:
                self.known[name] = category
                self.learned.append((name, category, "keyword"))
            return category
        # Evidence from this one row's raw text is used for this row and never remembered:
        # the payee it carries may be shared with rows it does not describe.
        category = keyword_category(description or "")
        if category:
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


# ---------- Review: the model checks proposed groups against the raw evidence ----------
REVIEW_BATCH = 60


def _clean_for_review(description):
    """Strip store and reference numbers so the model sees the words, not the noise."""
    text = re.sub(r"#?\d[\d\-]{3,}", " ", description or "")
    return re.sub(r"\s+", " ", text).strip()[:80]


def review_categories(items, api_key, model=MODEL, timeout=90):
    """Ask the model whether each proposed group fits its transaction.

    `items` is a list of dicts with id, description, payee, amount (signed), account_type
    and proposed. Returns {id: (category, reason)} for the items the model would change;
    agreement is silence. Only the cleaned description, payee, rounded amount, account
    kind and proposed group leave the machine. Raises on a transport error.
    """
    items = [i for i in items if i.get("proposed")]
    if not items or not api_key:
        return {}
    groups = "\n".join(f"- {key}: {what}" for key, what in GROUPS.items())
    extra = (
        f"- {CARD_PAYMENT_RECEIVED}: the cardholder's own payment arriving on a credit card\n"
        f"- {CARD_CREDIT}: statement credit, perk or fee reimbursement on a credit card\n"
        f"- {INTEREST}: bank interest earned\n"
        "- income:paycheck, income:other, bill:rent, bill:car_loan, bill:student_loan, bill:family, "
        "bill:debt_payment (a payment to a credit card from a bank account), transfer:internal, "
        "transfer:points_redemption: other groups that already exist and may be kept or chosen"
    )
    lines = []
    for i in items:
        kind = "credit card" if i.get("account_type") == "credit_card" else "bank account"
        amount = float(i.get("amount") or 0)
        direction = "charge" if amount < 0 else "credit/deposit"
        lines.append(
            f'{{"id": "{i["id"]}", "text": "{_clean_for_review(i.get("description"))}", '
            f'"payee": "{(i.get("payee") or "")[:40]}", "amount": {abs(round(amount))}, '
            f'"kind": "{kind} {direction}", "proposed": "{i["proposed"]}"}}'
        )
    prompt = (
        "You audit how a personal finance app grouped transactions from a US bank and credit card feed. "
        "The proposed groups came from generic merchant and keyword matching, so they can be wrong in "
        "obvious ways. For each item, decide whether the proposed group is right given the text, payee, "
        "amount and kind. "
        "Think about what the merchant actually is: a warehouse club's fuel pump is gas, not groceries; "
        "a pharmacy line at a supermarket is health; a restaurant chain is dining or fast food; "
        "a positive amount on a credit card is a refund (keep the merchant's spending group so it nets), "
        "a card payment received, or a statement credit. Bank-account debits paid to a person are Zelle payments; "
        "payments to a credit card issuer are bill:debt_payment. Money arriving in a bank account is income or a "
        "transfer, never spending. A refund of an ordinary purchase keeps its merchant's spending group. "
        "Be conservative: only change a group when a "
        "different one is clearly better, and never change a group merely because the evidence is thin; "
        "if you cannot tell, leave it.\n\nGroups:\n"
        f"{groups}\n{extra}\n\n"
        'Answer with a JSON array of objects {"id": ..., "category": ..., "reason": ...} listing ONLY the items '
        "you would change, with the reason in at most twelve words. Return [] if every proposed group is fine.\n\n"
        "Items:\n" + "\n".join(lines)
    )
    answers = _generate(prompt, api_key, model, timeout)
    if isinstance(answers, dict):
        answers = answers.get("changes") or answers.get("items") or []
    allowed = (
        set(GROUPS)
        | {CARD_PAYMENT_RECEIVED, CARD_CREDIT, INTEREST}
        | {
            "income:paycheck",
            "income:other",
            "bill:rent",
            "bill:car_loan",
            "bill:student_loan",
            "bill:family",
            "bill:debt_payment",
            "transfer:internal",
            "transfer:points_redemption",
        }
    )
    by_id = {str(i["id"]): i for i in items}
    result = {}
    for answer in answers if isinstance(answers, list) else []:
        if not isinstance(answer, dict):
            continue
        item = by_id.get(str(answer.get("id")))
        category = answer.get("category")
        if item and category in allowed and category != item["proposed"] and change_is_sane(item, category):
            result[item["id"]] = (category, str(answer.get("reason") or "")[:120])
    return result


def change_is_sane(item, category):
    """Hard limits on what the model may do, whatever it says: the sign of an amount and the
    kind of account rule some groups out. Wrong answers here would break the dashboard's totals."""
    amount = float(item.get("amount") or 0)
    on_card = item.get("account_type") == "credit_card"
    description = item.get("description") or ""
    if amount < 0:
        # A charge is never a refund, a card payment received, or income.
        return not (category.startswith(("refund:", "income:")) or category == CARD_PAYMENT_RECEIVED)
    if not on_card:
        # Money arriving in a bank account is income or a transfer, never spending or a bill.
        return not category.startswith(("spending:", "bill:"))
    if item.get("proposed", "").startswith("spending:") and category in (CARD_CREDIT, CARD_PAYMENT_RECEIVED):
        # A refund of an ordinary purchase keeps its merchant's group so it nets against the spending;
        # only text that says credit, reimbursement or payment makes it something else.
        return credit_wording(description) or "payment" in description.lower()
    return True
