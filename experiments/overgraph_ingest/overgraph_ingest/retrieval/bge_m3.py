"""BGE-M3 dense and sparse encoders. Loaded only when the experiment asks for them."""

from __future__ import annotations

import time
from collections.abc import Sequence
from typing import Any

BGE_M3_MODEL = "BAAI/bge-m3"
BGE_M3_DENSE_DIMENSION = 1024
BGE_M3_SPARSE_ENCODER_ID = "bge-m3-sparse-v1"
BGE_M3_BATCH_SIZE = 16

_MODEL: Any = None
_LOAD_SECONDS: float | None = None


def load_bge_m3() -> tuple[Any, float]:
    global _MODEL, _LOAD_SECONDS
    if _MODEL is not None:
        return _MODEL, 0.0
    try:
        from FlagEmbedding import BGEM3FlagModel
    except ImportError as exc:
        raise RuntimeError(
            "BGE-M3 requires FlagEmbedding. Install with: uv sync --extra local"
        ) from exc
    started = time.perf_counter()
    _MODEL = BGEM3FlagModel(BGE_M3_MODEL, use_fp16=False)
    _LOAD_SECONDS = time.perf_counter() - started
    return _MODEL, _LOAD_SECONDS


def bge_m3_load_seconds() -> float | None:
    return _LOAD_SECONDS


class BgeM3DenseEncoder:
    model = BGE_M3_MODEL
    dimension = BGE_M3_DENSE_DIMENSION

    def __init__(self, dimension: int = BGE_M3_DENSE_DIMENSION) -> None:
        if dimension != BGE_M3_DENSE_DIMENSION:
            raise ValueError(f"{BGE_M3_MODEL} requires dimension {BGE_M3_DENSE_DIMENSION}")
        load_bge_m3()

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        model, _loaded = load_bge_m3()
        vectors: list[list[float]] = []
        for start in range(0, len(texts), BGE_M3_BATCH_SIZE):
            batch = list(texts[start : start + BGE_M3_BATCH_SIZE])
            output = model.encode(
                batch,
                return_dense=True,
                return_sparse=False,
                return_colbert_vecs=False,
            )
            dense = output["dense_vecs"]
            for row in dense:
                vector = [float(value) for value in row]
                if len(vector) != self.dimension:
                    raise RuntimeError(
                        f"BGE-M3 dense has dimension {len(vector)}, expected {self.dimension}"
                    )
                vectors.append(vector)
        return vectors


class BgeM3SparseEncoder:
    encoder_id = BGE_M3_SPARSE_ENCODER_ID

    def __init__(self) -> None:
        load_bge_m3()

    def fit(self, texts: Sequence[str]) -> None:
        return None

    def embed(self, texts: Sequence[str]) -> list[list[tuple[int, float]]]:
        model, _loaded = load_bge_m3()
        encoded: list[list[tuple[int, float]]] = []
        for start in range(0, len(texts), BGE_M3_BATCH_SIZE):
            batch = list(texts[start : start + BGE_M3_BATCH_SIZE])
            output = model.encode(
                batch,
                return_dense=False,
                return_sparse=True,
                return_colbert_vecs=False,
            )
            for weights in output["lexical_weights"]:
                encoded.append(_sparse_weights(weights))
        return encoded


def _sparse_weights(weights: dict[object, object]) -> list[tuple[int, float]]:
    return sorted((int(index), float(value)) for index, value in weights.items())
