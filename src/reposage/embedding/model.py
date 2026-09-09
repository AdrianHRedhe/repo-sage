from sentence_transformers import SentenceTransformer


class Embedder:
    """Wraps a local sentence-transformers model.

    Uses the model's own named prompts ("query"/"document") when it declares
    them - Qwen3-Embedding ships an asymmetric instruction template for
    queries that measurably improves retrieval - and falls back to plain
    encoding for models that don't declare them, so EMBEDDING_MODEL stays
    swappable without code changes.
    """

    def __init__(self, model_name: str) -> None:
        self._model = SentenceTransformer(model_name)

    def _encode(self, texts: list[str], prompt_name: str) -> list[list[float]]:
        kwargs = {"prompt_name": prompt_name} if prompt_name in self._model.prompts else {}
        return self._model.encode(texts, **kwargs).tolist()

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._encode(texts, "document")

    def embed_query(self, text: str) -> list[float]:
        return self._encode([text], "query")[0]
