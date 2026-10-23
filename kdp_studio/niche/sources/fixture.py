"""Deterministic synthetic search results so the pipeline, scoring and reports can be
exercised and tested offline. Niche difficulty is derived from words in the keyword:
'mandala'/'adult coloring' -> saturated, 'bold and easy'/'seniors' -> open, otherwise mixed."""

from __future__ import annotations

import datetime as dt
import hashlib
import random

from ..models import BookObservation

PUBLISHERS_INDIE = ["Independently published"] * 7 + ["Blue Fern Press", "Marigold Studio", "Quiet Hands Books"]
PUBLISHERS_TRADE = ["Dover Publications", "Chronicle Books", "Penguin Workshop", "Sterling Children's Books"]
ADJ = ["Bold", "Easy", "Simple", "Relaxing", "Beautiful", "Cute", "Big", "Calm", "Happy", "Whimsical", "Gentle", "Vintage"]
NOUNS = ["Designs", "Patterns", "Pages", "Illustrations", "Scenes", "Garden", "Collection", "Edition", "Moments"]
SUFFIX = ["for Adults", "for Seniors", "for Kids", "for Women", "for Beginners", "for Relaxation", "for Stress Relief", "for Teens"]


def _profile(keyword: str) -> dict:
    k = keyword.lower()
    if any(w in k for w in ("mandala", "adult coloring", "coloring book for adults", "animals")):
        return {"bsr_center": 4.2, "rc_center": 2.9, "indie": 0.45, "fresh": 0.12, "price": 7.99}
    if any(w in k for w in ("bold and easy", "seniors", "large print", "dementia", "low vision")):
        return {"bsr_center": 4.6, "rc_center": 1.8, "indie": 0.85, "fresh": 0.45, "price": 9.99}
    if any(w in k for w in ("kids", "toddler", "children")):
        return {"bsr_center": 4.4, "rc_center": 2.4, "indie": 0.6, "fresh": 0.3, "price": 7.49}
    return {"bsr_center": 5.1, "rc_center": 2.1, "indie": 0.7, "fresh": 0.25, "price": 8.99}


class FixtureSource:
    name = "fixture"

    def __init__(self, seed: int = 1, store: str = "Books"):
        self.seed = seed
        self.store = store

    def search(self, keyword: str, max_books: int) -> list[BookObservation]:
        rng = random.Random(hashlib.sha256(f"{self.seed}:{keyword}".encode()).hexdigest())
        prof = _profile(keyword)
        books: list[BookObservation] = []
        core = " ".join(w.capitalize() for w in keyword.split()[:3])
        for pos in range(1, max_books + 1):
            bsr = int(10 ** rng.gauss(prof["bsr_center"] + pos * 0.02, 0.45))
            rc = int(10 ** rng.gauss(prof["rc_center"], 0.6))
            indie = rng.random() < prof["indie"]
            age = int(rng.expovariate(1 / 500)) if rng.random() > prof["fresh"] else rng.randint(10, 365)
            price = round(prof["price"] + rng.choice([-2, -1, 0, 0, 1, 2, 3]) , 2)
            title = f"{rng.choice(ADJ)} {core} {rng.choice(NOUNS)}: {rng.choice(ADJ)} Coloring Book {rng.choice(SUFFIX)} with {rng.choice([25, 30, 40, 50])} {rng.choice(NOUNS)}"
            books.append(
                BookObservation(
                    keyword=keyword,
                    source=self.name,
                    asin=f"B0FX{rng.randrange(16**6):06X}",
                    title=title,
                    author=f"{rng.choice(['Mia', 'Lena', 'Harper', 'Noah', 'Ivy', 'Owen'])} {rng.choice(['Hart', 'Lane', 'Wells', 'Reed', 'Shaw'])}",
                    price=max(3.99, price),
                    currency="USD",
                    bsr=max(1, bsr),
                    bsr_store=self.store,
                    rating=round(rng.uniform(4.2, 4.9), 1),
                    rating_count=max(0, rc),
                    pub_date=dt.date.today() - dt.timedelta(days=age),
                    pages=rng.choice([52, 64, 76, 88, 104]),
                    publisher=rng.choice(PUBLISHERS_INDIE) if indie else rng.choice(PUBLISHERS_TRADE),
                    format="Paperback",
                    position=pos,
                    url=None,
                )
            )
        return books
