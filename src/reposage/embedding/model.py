# Bounds on a single encode() call. Both exist because this process is
# memory-capped and, via the web sandbox, embeds repos nobody has vetted -
# an unbounded encode is a remote OOM-kill, not just a slow request.
#
# Measured on linux/arm64 (Qwen3-Embedding-0.6B, fp32, CPU), peak RSS for a
# full batch of maximum-length chunks:
#
#   max_seq  batch   peak RSS    (model load alone: 3.99GB)
#      512     4       3.99GB
#     1024     4       4.90GB
#     2048     4       5.91GB
#     2048     2       4.90GB
#
# sentence-transformers defaults to batch_size=32 and this model declares
# max_seq_length=32768, which together were reliably OOM-killed: the encode
# pads every text in a batch to the longest one in it, so cost scales with
# batch x longest-chunk, and it sorts longest-first so the very first batch
# is the worst one. Larger batches also measured *slower* here (89 real
# chunks: 48s at batch 4, 61s at batch 8), since on CPU the padding waste
# outweighs any batching win - so the small batch costs nothing.
#
# 2048 was chosen over 1024 because it truncates nothing in practice (the
# longest real chunk measured across this project's repos was 1117 tokens,
# median 104), while still bounding the worst case to ~5.9GB.
MAX_SEQ_LENGTH = 2048
ENCODE_BATCH_SIZE = 4


class Embedder:
    """Wraps a local sentence-transformers model.

    Uses the model's own named prompts ("query"/"document") when it declares
    them - Qwen3-Embedding ships an asymmetric instruction template for
    queries that measurably improves retrieval - and falls back to plain
    encoding for models that don't declare them, so EMBEDDING_MODEL stays
    swappable without code changes.
    """

    def __init__(self, model_name: str) -> None:
        from sentence_transformers import SentenceTransformer  # heavy import, defer until first use

        self._model = SentenceTransformer(model_name)
        # Only ever lower it - a model whose own limit is already below this
        # knows better than we do.
        self._model.max_seq_length = min(self._model.max_seq_length, MAX_SEQ_LENGTH)

    def _encode(self, texts: list[str], prompt_name: str) -> list[list[float]]:
        kwargs = {"prompt_name": prompt_name} if prompt_name in self._model.prompts else {}
        return self._model.encode(texts, batch_size=ENCODE_BATCH_SIZE, **kwargs).tolist()

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._encode(texts, "document")

    def embed_query(self, text: str) -> list[float]:
        return self._encode([text], "query")[0]
