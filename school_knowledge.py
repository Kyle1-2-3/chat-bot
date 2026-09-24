"""Search the reviewed public-site snapshot; never fetch private student data."""
from collections import Counter
from functools import lru_cache
import json
import logging
import math
from pathlib import Path
import re
import unicodedata

KNOWLEDGE_PATH = Path(__file__).resolve().parent / "data" / "school_knowledge.json"
STOPWORDS = set("a an the is are was were who what when how where why which can do does i my me you your about at of on in for to and or with school brentwood please tell have has it there".split())
ALIASES = {"math": "mathematics", "maths": "mathematics", "hiuse": "house",
           "whittal": "whittall", "mack": "mackenzie", "alex": "alexandra",
           "mr": "", "mrs": "", "ms": "", "facilities": "facility",
           "teachers": "teacher", "coaches": "coach", "houseparents": "houseparent",
           "sports": "sport", "arts": "art", "wifi": "wifi"}
PLACE_NAMES = set("foote crooks maeda killy bunch mcneill innovations rogers allard hope alexandra mackenzie privett ellis whittall".split())


def tokens(text):
    text = unicodedata.normalize("NFKD", text.lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"house\s+parents?", "houseparent", text)
    text = re.sub(r"wi[ -]fi", "wifi", text)
    return [ALIASES.get(t, t) for t in re.findall(r"[a-z0-9]+", text)
            if t not in STOPWORDS and ALIASES.get(t, t)]


@lru_cache(maxsize=1)
def load_knowledge():
    try:
        data = json.loads(KNOWLEDGE_PATH.read_text(encoding="utf-8"))
        records = data["records"]
        if not isinstance(records, list):
            raise ValueError("records must be a list")
        return data
    except (OSError, ValueError, KeyError):
        logging.getLogger("chatbot").exception("Public school knowledge is unavailable")
        return {"checked_on": None, "records": []}


def search_school_knowledge(search_query, limit=8):
    """Bounded lexical retrieval with title weighting and no unrelated fallback."""
    data = load_knowledge()
    records = data["records"]
    terms = set(tokens(search_query))
    if not terms or not records:
        return []
    docs = [Counter(tokens(r["title"] + " " + " ".join(r.get("keywords", []))
                           + " " + " ".join(r["facts"]))) for r in records]
    named_terms = PLACE_NAMES | {t for r in records if r.get("category") == "staff"
                                for t in tokens(r["title"]) if len(t) > 2}
    anchors = terms & named_terms
    frequency = Counter(t for doc in docs for t in doc)
    average_length = sum(sum(d.values()) for d in docs) / len(docs)
    scored = []
    for record, doc in zip(records, docs):
        matches = terms & doc.keys()
        if not matches or (anchors and not anchors.intersection(doc)):
            continue
        title = set(tokens(record["title"]))
        length = sum(doc.values())
        score = 0
        for term in matches:
            idf = math.log(1 + (len(docs) - frequency[term] + .5) / (frequency[term] + .5))
            tf = doc[term]
            score += idf * (tf * 2.2 / (tf + 1.2 * (.25 + .75 * length / average_length)))
            if term in title:
                score += idf * 1.5
        score *= len(matches) / len(terms)
        scored.append((score, record))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    if not scored:
        return []
    cutoff = max(.1, scored[0][0] * .22)
    return [{**record, "checked_on": data["checked_on"]}
            for score, record in scored[:max(1, min(limit, 12))] if score >= cutoff]
