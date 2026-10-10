"""Dense and sparse encoders. Sequential only; no worker pool."""

from __future__ import annotations

import hashlib
import math
import re
from collections import Counter
from collections.abc import Sequence
from typing import Protocol

from overgraph_ingest.ids import normalize_text

DENSE_MODEL = "text-embedding-3-large"
DENSE_DIMENSION = 3072
SPARSE_DIMENSIONS = 262144
SPARSE_ENCODER_ID = "lexical-tfidf-hash-v1"
TOKEN_RE = re.compile(r"[a-zåäö0-9]+")
STOPWORDS = frozenset(
    {
        "att",
        "av",
        "de",
        "den",
        "det",
        "en",
        "ett",
        "från",
        "för",
        "har",
        "i",
        "innehåller",
        "kan",
        "med",
        "och",
        "om",
        "på",
        "ska",
        "som",
        "till",
        "vilka",
        "vilket",
        "är",
    }
)
_STEM_SUFFIXES = (
    "ningarna",
    "ningar",
    "ningen",
    "ning",
    "ades",
    "ande",
    "ade",
    "ar",
    "at",
    "as",
    "er",
    "or",
    "en",
    "et",
    "na",
    "a",
    "s",
    "t",
    "e",
)


class DenseEncoder(Protocol):
    model: str
    dimension: int

    def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


def tokenize(text: str) -> list[str]:
    return [
        stemmed
        for token in TOKEN_RE.findall(normalize_text(text).casefold())
        if (stemmed := stem(token)) and stemmed not in STOPWORDS
    ]


def stem(token: str) -> str:
    for suffix in _STEM_SUFFIXES:
        kept = len(token) - len(suffix)
        if kept >= 4 and token.endswith(suffix):
            return token[:kept]
    return token


def hashed_sparse(text: str, *, dimensions: int = SPARSE_DIMENSIONS) -> list[tuple[int, float]]:
    tokens = tokenize(text)
    grams = tokens + [f"{left}_{right}" for left, right in zip(tokens, tokens[1:], strict=False)]
    counts: Counter[int] = Counter(
        int(hashlib.sha256(gram.encode("utf-8")).hexdigest(), 16) % dimensions for gram in grams
    )
    return [(index, float(weight)) for index, weight in sorted(counts.items())]


class LexicalSparseEncoder:
    encoder_id = SPARSE_ENCODER_ID
    dimensions = SPARSE_DIMENSIONS

    def __init__(self) -> None:
        self.idf: dict[int, float] = {}

    def fit(self, texts: Sequence[str]) -> None:
        document_frequency: Counter[int] = Counter()
        for text in texts:
            document_frequency.update(
                {index for index, _weight in hashed_sparse(text, dimensions=self.dimensions)}
            )
        count = max(len(texts), 1)
        self.idf = {
            index: math.log((count + 1) / (frequency + 1)) + 1.0
            for index, frequency in document_frequency.items()
        }

    def embed(self, texts: Sequence[str]) -> list[list[tuple[int, float]]]:
        encoded: list[list[tuple[int, float]]] = []
        for text in texts:
            raw = hashed_sparse(text, dimensions=self.dimensions)
            encoded.append(
                [(index, weight * self.idf.get(index, 1.0)) for index, weight in raw]
            )
        return encoded


class HashedDenseEncoder:
    """Deterministic lexical dense vectors for tests and model-free dry runs."""

    def __init__(self, dimension: int) -> None:
        if dimension < 1:
            raise ValueError("dense dimension must be >= 1")
        self.model = "hashed-dense-v1"
        self.dimension = dimension

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return [_hashed_dense(text, self.dimension) for text in texts]


class OpenAIDenseEncoder:
    def __init__(
        self,
        *,
        api_key: str,
        model: str = DENSE_MODEL,
        dimension: int = DENSE_DIMENSION,
        base_url: str | None = None,
        batch_size: int = 64,
    ) -> None:
        if not api_key.strip():
            raise ValueError("openai api key is required")
        if model == DENSE_MODEL and dimension != DENSE_DIMENSION:
            raise ValueError(f"{DENSE_MODEL} requires dimension {DENSE_DIMENSION}")
        from openai import OpenAI

        options: dict[str, str] = {"api_key": api_key}
        if base_url:
            options["base_url"] = base_url
        self._client = OpenAI(**options)
        self.model = model
        self.dimension = dimension
        self.batch_size = batch_size

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for start in range(0, len(texts), self.batch_size):
            batch = list(texts[start : start + self.batch_size])
            response = self._client.embeddings.create(model=self.model, input=batch)
            ordered = sorted(response.data, key=lambda item: item.index)
            for item in ordered:
                vector = list(item.embedding)
                if len(vector) != self.dimension:
                    raise RuntimeError(
                        f"embedding has dimension {len(vector)}, expected {self.dimension}"
                    )
                vectors.append(vector)
        return vectors


def cosine(left: Sequence[float], right: Sequence[float]) -> float:
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    norm_left = math.sqrt(sum(value * value for value in left))
    norm_right = math.sqrt(sum(value * value for value in right))
    if norm_left == 0 or norm_right == 0:
        return 0.0
    return dot / (norm_left * norm_right)


def sparse_dot(left: Sequence[tuple[int, float]], right: Sequence[tuple[int, float]]) -> float:
    weights = dict(left)
    return sum(weights.get(index, 0.0) * value for index, value in right)


def _hashed_dense(text: str, dimension: int) -> list[float]:
    vector = [0.0] * dimension
    for token in tokenize(text):
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        index = int.from_bytes(digest[:4], "big") % dimension
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vector[index] += sign
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0:
        return vector
    return [value / norm for value in vector]
