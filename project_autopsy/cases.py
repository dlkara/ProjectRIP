from __future__ import annotations

import json
import math
import re
from collections import Counter
from pathlib import Path


def grams(value: str) -> Counter[str]:
    words = re.findall(r"[가-힣a-zA-Z0-9]+", value.lower())
    result: Counter[str] = Counter()
    for word in words:
        if len(word) <= 2:
            result[word] += 1
        else:
            for size in (2, 3):
                for index in range(len(word) - size + 1):
                    result[word[index : index + size]] += 1
    return result


class CaseCatalog:
    def __init__(self, path: Path):
        self.cases = json.loads(path.read_text(encoding="utf-8"))
        ids = [case["id"] for case in self.cases]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate case ID")
        for case in self.cases:
            if case["excerpt"] not in case["story"]:
                raise ValueError(f"Excerpt is not in source text: {case['id']}")
            if case["source_type"] not in {"fictional_sample", "public_source", "user_uploaded"}:
                raise ValueError(f"Invalid source type: {case['id']}")
        self.by_id = {case["id"]: case for case in self.cases}
        self.documents = [
            grams(" ".join([case["mechanism"]] * 2 + case["tags"] * 3 + [case["story"]]))
            for case in self.cases
        ]
        self.document_frequency = Counter(
            gram for document in self.documents for gram in document.keys()
        )

    def search(self, query: str, limit: int = 8) -> list[dict]:
        query_terms = grams(query)
        if not query_terms:
            return []
        total = len(self.cases)
        idf = {
            term: math.log((total + 1) / (self.document_frequency.get(term, 0) + 1)) + 1
            for term in query_terms
        }
        query_norm = math.sqrt(sum((count * idf[term]) ** 2 for term, count in query_terms.items()))
        matches = []
        for case, document in zip(self.cases, self.documents):
            dot = sum(query_terms[term] * document.get(term, 0) * weight**2 for term, weight in idf.items())
            document_norm = math.sqrt(
                sum((count * idf.get(term, 1)) ** 2 for term, count in document.items())
            )
            score = dot / (query_norm * document_norm) if document_norm and query_norm else 0.0
            if score > 0:
                matches.append({**case, "score": round(score, 4)})
        return sorted(matches, key=lambda item: item["score"], reverse=True)[:limit]

    def public_metadata(self) -> list[dict]:
        return [
            {key: case[key] for key in ("id", "title", "source_type", "mechanism", "tags", "story", "excerpt")}
            for case in self.cases
        ]
