"""
Embedding provider adapter — the single path used by query-time semantic
search, background index builds, and management commands.

Two providers are supported:
- 'sentence-transformers' (local model, CPU)
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
        # CPU keeps this off GPU memory and avoids CUDA version issues.
        # token authenticates HF Hub requests (required for gated models;
        # also silences the unauthenticated-request warnings).
        self._model = SentenceTransformer(model_name, device='cpu', token=token or None)
        self._dimensions = int(self._model.get_sentence_embedding_dimension())
        if expected_dim and self._dimensions != expected_dim:
            raise EmbeddingUnavailableError(
                f"Model '{model_name}' produces {self._dimensions}-dim embeddings; "
                f"the configuration declares {expected_dim}. Fix embedding_dimension "
                f"on the configuration to match the model's actual output."
            )

    @property
    def dimensions(self):
        return self._dimensions

    def embed_texts(self, texts: List[str]) -> List[List[float]]:
        embeddings = self._model.encode(list(texts))
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
