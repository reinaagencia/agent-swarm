"""
🧬 EmbeddingService — Generación de embeddings locales con fastembed.

Usa BAAI/bge-small-en-v1.5 (384 dimensiones) vía fastembed.
Corre 100% local, sin API keys, sin costos, sin límites.
"""

from __future__ import annotations
import numpy as np
from typing import Any


class EmbeddingService:
    """Genera embeddings de texto usando fastembed local.

    Uso:
        emb = EmbeddingService()
        vector = emb.embed("Texto a vectorizar")  # list[float] 384d
        vectors = emb.embed_batch(["texto1", "texto2"])  # list[list[float]]
    """

    def __init__(self, model_name: str = "BAAI/bge-small-en-v1.5"):
        self.model_name = model_name
        self._model = None
        self._dims = 384

    @property
    def model(self):
        if self._model is None:
            from fastembed import TextEmbedding
            self._model = TextEmbedding(self.model_name)
        return self._model

    @property
    def dimensions(self) -> int:
        return self._dims

    def embed(self, text: str) -> list[float]:
        """Genera embedding para un texto.

        Args:
            text: Texto a vectorizar

        Returns:
            list[float]: Vector de 384 dimensiones
        """
        if not text or not text.strip():
            return [0.0] * self._dims

        result = list(self.model.embed(text))
        if result:
            vector = result[0]
            if hasattr(vector, 'tolist'):
                return vector.tolist()
            return list(vector)
        return [0.0] * self._dims

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Genera embeddings para múltiples textos (batch optimizado).

        Args:
            texts: Lista de textos a vectorizar

        Returns:
            list[list[float]]: Lista de vectores 384d
        """
        if not texts:
            return []

        results = []
        for embedding in self.model.embed(texts):
            if hasattr(embedding, 'tolist'):
                results.append(embedding.tolist())
            else:
                results.append(list(embedding))
        return results

    def embed_chunks(self, texts: list[str], batch_size: int = 32) -> list[list[float]]:
        """Genera embeddings por lotes, ideal para chunks de conversación.

        Args:
            texts: Textos a vectorizar
            batch_size: Tamaño del lote

        Returns:
            list[list[float]]: Vectores 384d
        """
        results = []
        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]
            results.extend(self.embed_batch(batch))
        return results

    def similarity(self, vec_a: list[float], vec_b: list[float]) -> float:
        """Calcula similitud coseno entre dos vectores."""
        a = np.array(vec_a)
        b = np.array(vec_b)
        norm_a = np.linalg.norm(a)
        norm_b = np.linalg.norm(b)
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return float(np.dot(a, b) / (norm_a * norm_b))
