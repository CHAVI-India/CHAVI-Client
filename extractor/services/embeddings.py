"""
Embedding provider adapter — the single path used by query-time semantic
search, background index builds, and management commands.

Two providers are supported:
- 'sentence-transformers' (local model; CUDA is auto-detected per process and
  falls back to CPU — GPU containers need the device granted via compose)
- 'openai' / 'openai-compatible' (any OpenAI-compatible /embeddings endpoint,
  including remote OpenAI, Azure-style endpoints, or a local Ollama server)

Each EmbeddingConfiguration declares its own embedding_dimension; providers
verify the model's real output against that declaration. The storage column
is dimensionless — different configs may use different dimensions.
"""

from typing import List, Optional
from logging import getLogger

from openai import OpenAI

log = getLogger(__name__)


class EmbeddingUnavailableError(Exception):
    """Raised when embeddings cannot be computed for the active configuration."""


class _CudaSmokeTestFailed(Exception):
    """Internal signal: model loaded on CUDA but a warmup encode failed."""


def _resolve_device() -> str:
    """
    Pick 'cuda' only when a GPU is present AND this torch build ships kernels
    for its compute capability. is_available() alone is not enough: it returns
    True for GPUs whose kernels aren't compiled in (e.g. an sm_50 card with a
    torch cu13x build supporting sm_75+), where the first encode would crash
    mid-task. Any detection error resolves to 'cpu'.
    """
    try:
        import torch
        if not torch.cuda.is_available():
            return 'cpu'
        major, minor = torch.cuda.get_device_capability(0)
        arch = f'sm_{major}{minor}'
        if arch not in torch.cuda.get_arch_list():
            log.warning(
                f"GPU '{torch.cuda.get_device_name(0)}' ({arch}) is not supported "
                f"by this torch build {torch.cuda.get_arch_list()}; using CPU"
            )
            return 'cpu'
        return 'cuda'
    except Exception as e:
        log.warning(f"CUDA detection failed ({e}); using CPU")
        return 'cpu'


class BaseEmbeddingProvider:
    name = 'base'

    def embed_texts(self, texts: List[str]) -> List[List[float]]:
        raise NotImplementedError

    @property
    def dimensions(self) -> Optional[int]:
        return None


class SentenceTransformerProvider(BaseEmbeddingProvider):
    name = 'sentence-transformers'

    def __init__(self, model_name: str, expected_dim: Optional[int] = None,
                 token: Optional[str] = None):
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as e:
            raise EmbeddingUnavailableError(
                "sentence-transformers is not installed. "
                "Install it with: pip install sentence-transformers"
            ) from e
        # token authenticates HF Hub requests (required for gated models;
        # also silences the unauthenticated-request warnings).
        self._device = _resolve_device()
        try:
            self._model = self._load_model(SentenceTransformer, model_name,
                                           self._device, token)
        except _CudaSmokeTestFailed:
            self._device = 'cpu'
            self._model = self._load_model(SentenceTransformer, model_name,
                                           'cpu', token)
        self._dimensions = int(self._model.get_sentence_embedding_dimension())
        if expected_dim and self._dimensions != expected_dim:
            raise EmbeddingUnavailableError(
                f"Model '{model_name}' produces {self._dimensions}-dim embeddings; "
                f"the configuration declares {expected_dim}. Fix embedding_dimension "
                f"on the configuration to match the model's actual output."
            )
        log.info(f"Embedding model '{model_name}' loaded on {self._device}")

    @staticmethod
    def _load_model(SentenceTransformer, model_name, device, token):
        model = SentenceTransformer(model_name, device=device, token=token or None)
        if device == 'cuda':
            # Detection can still pass on an unusable GPU (driver mismatch,
            # init-time OOM) — verify with a real encode so a bad GPU falls
            # back to CPU here instead of dying mid-batch in a Celery task.
            try:
                model.encode(['warmup'], show_progress_bar=False)
            except Exception:
                log.warning("GPU smoke test failed; falling back to CPU",
                            exc_info=True)
                raise _CudaSmokeTestFailed
        return model

    @property
    def dimensions(self):
        return self._dimensions

    def embed_texts(self, texts: List[str]) -> List[List[float]]:
        # Larger batches pay off on GPU; 32 is the encode() default.
        batch_size = 64 if self._device == 'cuda' else 32
        embeddings = self._model.encode(
            list(texts), batch_size=batch_size, show_progress_bar=False)
        return embeddings.tolist()


class OpenAICompatibleProvider(BaseEmbeddingProvider):
    name = 'openai'
    BATCH_SIZE = 100

    def __init__(self, model_name: str, api_key: str, base_url: Optional[str] = None,
                 expected_dim: Optional[int] = None):
        kwargs = {'api_key': api_key or 'not-needed'}
        if base_url:
            url = base_url.rstrip('/')
            if not url.startswith(('http://', 'https://')):
                url = f'http://{url}'
            kwargs['base_url'] = url
        self._client = OpenAI(**kwargs)
        self._model_name = model_name
        self._expected_dim = expected_dim

    def embed_texts(self, texts: List[str]) -> List[List[float]]:
        out: List[List[float]] = []
        for i in range(0, len(texts), self.BATCH_SIZE):
            batch = texts[i:i + self.BATCH_SIZE]
            kwargs = {'model': self._model_name, 'input': batch}
            # dimensions= is an OpenAI v3-embedding parameter; other endpoints
            # may reject it, so only send it where it's supported
            if 'text-embedding-3' in self._model_name and self._expected_dim:
                kwargs['dimensions'] = self._expected_dim
            response = self._client.embeddings.create(**kwargs)
            vectors = [item.embedding for item in response.data]
            for v in vectors:
                if self._expected_dim and len(v) != self._expected_dim:
                    raise EmbeddingUnavailableError(
                        f"Provider returned {len(v)}-dim embedding; "
                        f"the configuration declares {self._expected_dim}. "
                        f"Fix embedding_dimension or the endpoint's model."
                    )
            out.extend(vectors)
        return out


def build_provider(config) -> BaseEmbeddingProvider:
    """
    Construct the provider for an EmbeddingConfiguration.
    """
    provider = (config.model_provider or '').lower()
    if provider in ('sentence-transformers', 'local', 'huggingface'):
        return SentenceTransformerProvider(
            config.model_name, config.embedding_dimension, token=config.api_key)
    if provider in ('openai', 'openai-compatible', 'ollama', 'azure'):
        return OpenAICompatibleProvider(
            model_name=config.model_name,
            api_key=config.api_key or '',
            base_url=config.base_url,
            expected_dim=config.embedding_dimension,
        )
    raise EmbeddingUnavailableError(f"Unsupported embedding provider: {config.model_provider}")


_provider_cache = {}


def get_provider(config) -> BaseEmbeddingProvider:
    """
    Cached provider per configuration (keyed on id + updated_at so edits
    reload the model).
    """
    key = (config.id, config.updated_at)
    if key not in _provider_cache:
        _provider_cache[key] = build_provider(config)
    return _provider_cache[key]
