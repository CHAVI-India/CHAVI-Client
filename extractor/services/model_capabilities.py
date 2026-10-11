"""
Discover model capabilities by querying the provider after basic configuration.

Based on provider documentation:
  - Ollama:        POST /api/show?model={name}  →  capabilities[], thinking.{values,default}, model_info
  - OpenAI-compat: minimal test call, inspect response for reasoning_tokens
  - Anthropic:     model-name pattern matching (Claude 4.5 vs 4.6+ use different thinking APIs)

Returns a normalised dict:
{
    "reasoning": bool,              # model supports extended reasoning/thinking
    "reasoning_levels": [str|bool],# e.g. ["low","medium","high"] or [false, true]
    "reasoning_default": str|bool,  # the model's default thinking level
    "context_length": int|None,     # actual context window from provider
    "vision": bool,                 # accepts image inputs
    "tools": bool,                  # supports function/tool calling
    "discovered_at": str,           # ISO timestamp
    "source": str,                  # "ollama" | "openai_probe" | "anthropic" | "name_heuristic" | "failed"
    "provider_hint": str,           # which API parameter to use for reasoning
    "model_details": dict,          # raw provider details (family, size, etc.)
}
"""
from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Any, Dict, Optional

import requests

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Heuristic patterns (fallback when no API discovery is available)
# ---------------------------------------------------------------------------

_REASONING_MODEL_PATTERNS = [
    r'\bo[13]\b',                    # OpenAI o1, o3
    r'\bo[13]-(mini|pro)\b',
    r'gpt-oss',                      # OpenAI gpt-oss
    r'gpt-5',                        # GPT-5 series
    r'gpt-6',                        # GPT-6 series
    r'deepseek.*r1',                 # DeepSeek R1
    r'\bqwq\b',                       # Qwen QwQ
    r'\br1\b',                        # generic R1 suffix
    r'qwen3',                        # Qwen 3 (has thinking mode)
]

_VISION_MODEL_PATTERNS = [
    r'gpt-4o',
    r'claude',
    r'gemini',
    r'llama.*vision',
    r'minicpm',
    r'qwen.*vl',
    r'phi-?3.*vision',
    r'gemma',
]


def _is_reasoning_model(model_name: str) -> bool:
    name = model_name.lower()
    return any(re.search(p, name) for p in _REASONING_MODEL_PATTERNS)


def _is_vision_model(model_name: str) -> bool:
    name = model_name.lower()
    return any(re.search(p, name) for p in _VISION_MODEL_PATTERNS)


# ---------------------------------------------------------------------------
# Ollama discovery — POST /api/show
# ---------------------------------------------------------------------------

def _discover_ollama(base_url: str, model_name: str) -> Dict[str, Any]:
    """
    Query Ollama's POST /api/show endpoint for model details.

    Per Ollama docs:
      - capabilities: list of supported features ("completion", "thinking", "vision", etc.)
      - thinking: {values: [...], default: ...} — values are booleans or named level strings
      - model_info: architecture metadata including context_length
      - details: {family, parameter_size, quantization_level, format}
    """
    result: Dict[str, Any] = {}
    normalized = base_url.rstrip('/')

    try:
        show_url = f"{normalized}/api/show"
        resp = requests.post(show_url, json={"model": model_name}, timeout=15)
        if resp.ok:
            data = resp.json()

            capabilities = data.get('capabilities', [])
            thinking = data.get('thinking')
            details = data.get('details', {})
            model_info = data.get('model_info', {})

            # Capabilities
            result['vision'] = 'vision' in capabilities
            result['tools'] = 'tools' in capabilities or 'function' in capabilities

            # Thinking / reasoning
            if thinking:
                values = thinking.get('values', [])
                default = thinking.get('default')
                # values: [false] means no thinking; [true, false] means on/off;
                # ["low", "medium", "high"] means named levels
                if values == [False]:
                    result['reasoning'] = False
                    result['reasoning_levels'] = []
                    result['reasoning_default'] = None
                else:
                    result['reasoning'] = True
                    result['reasoning_levels'] = values
                    result['reasoning_default'] = default
            else:
                # No thinking metadata — model may still think internally
                result['reasoning'] = 'thinking' in capabilities
                if result['reasoning']:
                    result['reasoning_levels'] = [True, False]
                    result['reasoning_default'] = True
                else:
                    result['reasoning'] = False
                    result['reasoning_levels'] = []
                    result['reasoning_default'] = None

            # Context length from model_info (key varies by architecture)
            ctx = None
            for key, val in model_info.items():
                if key.endswith('.context_length') or key == 'context_length':
                    ctx = int(val)
                    break
            if ctx:
                result['context_length'] = ctx

            # Store raw details for display
            result['model_details'] = {
                'family': details.get('family'),
                'parameter_size': details.get('parameter_size'),
                'quantization_level': details.get('quantization_level'),
                'format': details.get('format'),
            }

            # How to pass the thinking param via OpenAI-compat endpoint
            result['provider_hint'] = 'ollama_think'  # use extra_body={"think": value}

            result['source'] = 'ollama'
            return result

    except Exception as e:
        log.warning(f"Ollama /api/show failed for {model_name}: {e}")

    # Fallback: name heuristics
    result['reasoning'] = _is_reasoning_model(model_name)
    result['reasoning_levels'] = [True, False] if result['reasoning'] else []
    result['reasoning_default'] = True if result['reasoning'] else None
    result['vision'] = _is_vision_model(model_name)
    result['tools'] = False
    result['context_length'] = None
    result['model_details'] = {}
    result['provider_hint'] = 'ollama_think'
    result['source'] = 'name_heuristic'
    return result


# ---------------------------------------------------------------------------
# OpenAI-compatible discovery
# ---------------------------------------------------------------------------

# Known reasoning_effort values per OpenAI docs:
# none, minimal, low, medium, high, xhigh, max
# (subset supported per model — check model docs)
OPENAI_REASONING_LEVELS = ['none', 'low', 'medium', 'high']


def _discover_openai_compatible(base_url: str, model_name: str,
                                api_key: str, timeout: int = 30) -> Dict[str, Any]:
    """
    Discover capabilities for OpenAI-compatible endpoints by making a
    minimal test call and inspecting the response for reasoning tokens.

    Per OpenAI docs:
      - Chat Completions API: `reasoning_effort` param (none/low/medium/high)
      - Response usage includes: completion_tokens_details.reasoning_tokens
    """
    result: Dict[str, Any] = {}
    normalized = base_url.rstrip('/')

    # Ensure URL ends at /v1 for the OpenAI SDK
    if not normalized.endswith('/v1'):
        api_url = f"{normalized}/v1"
    else:
        api_url = normalized

    # Step 1: Try GET /models/{name} for metadata (some providers support this)
    try:
        resp = requests.get(
            f"{api_url}/models/{model_name}",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=10,
        )
        if resp.ok:
            data = resp.json()
            # Some third-party providers include extra fields
            if 'context_length' in data:
                result['context_length'] = int(data['context_length'])
            if 'max_output_tokens' in data:
                result['max_output_tokens'] = int(data['max_output_tokens'])
    except Exception as e:
        log.debug(f"GET /models/{model_name} failed: {e}")

    # Step 2: Minimal test call to probe reasoning support
    try:
        from openai import OpenAI
        client = OpenAI(
            base_url=api_url,
            api_key=api_key,
            timeout=timeout,
            max_retries=0,
        )
        response = client.chat.completions.create(
            model=model_name,
            messages=[{'role': 'user', 'content': 'Say "ok"'}],
            max_tokens=32,
        )

        # Inspect usage for reasoning tokens
        usage = response.usage
        if usage:
            completion_details = getattr(usage, 'completion_tokens_details', None)
            if completion_details:
                reasoning_tokens = getattr(completion_details, 'reasoning_tokens', 0)
                if reasoning_tokens and reasoning_tokens > 0:
                    result['reasoning'] = True

        # Also check if total completion tokens >> visible output
        if not result.get('reasoning'):
            completion_tokens = getattr(usage, 'completion_tokens', 0)
            visible = response.choices[0].message.content or ''
            visible_est = max(len(visible) // 4, 1)
            if completion_tokens > visible_est * 4:
                result['reasoning'] = True

        result['source'] = 'openai_probe'

    except Exception as e:
        log.warning(f"OpenAI-compatible probe failed for {model_name}: {e}")
        # Fall back to name heuristics
        result['reasoning'] = _is_reasoning_model(model_name)
        result['source'] = 'name_heuristic'

    # Fill in remaining fields
    result.setdefault('reasoning', False)
    result['vision'] = _is_vision_model(model_name)
    result['tools'] = True       # most OpenAI-compat endpoints support tools
    result['model_details'] = {}

    # Reasoning levels: standard OpenAI values (model-dependent subset)
    if result['reasoning']:
        result['reasoning_levels'] = OPENAI_REASONING_LEVELS
        result['reasoning_default'] = 'medium'
        result['provider_hint'] = 'openai_reasoning_effort'  # reasoning_effort param
    else:
        result['reasoning_levels'] = []
        result['reasoning_default'] = None
        result['provider_hint'] = None

    return result


# ---------------------------------------------------------------------------
# Anthropic discovery
# ---------------------------------------------------------------------------

def _discover_anthropic(model_name: str, api_key: str,
                        timeout: int = 30) -> Dict[str, Any]:
    """
    Discover capabilities for Anthropic models.

    Per Anthropic docs:
      - Claude 4.5 and earlier: thinking: {type: "enabled", budget_tokens: N} (min 1024)
      - Claude 4.6:             thinking: {type: "adaptive"} + output_config: {effort: ...}
                                (budget_tokens deprecated but still works)
      - Claude 4.7+:            ONLY thinking: {type: "adaptive"}
                                (type:"enabled" returns 400 error)

    Effort levels for adaptive thinking: "low", "medium", "high"
    """
    result: Dict[str, Any] = {}
    name = model_name.lower()

    # Determine model generation
    is_claude_4_7_plus = bool(re.search(
        r'claude-(opus|sonnet|haiku)-[5-9]|\bclaude-(opus|sonnet|haiku)-4\.[7-9]', name))
    is_claude_4_6 = bool(re.search(
        r'claude-(opus|sonnet|haiku)-4\.6', name))
    is_claude_4_5_or_earlier = bool(re.search(
        r'claude-(opus|sonnet|haiku)-4\.[0-5]|\bclaude-(sonnet|opus|haiku)-3', name))

    # All Claude 3+ models support vision and tools
    result['vision'] = True
    result['tools'] = True
    result['model_details'] = {'generation': 'claude'}

    if is_claude_4_7_plus:
        # Adaptive thinking only
        result['reasoning'] = True
        result['reasoning_levels'] = ['low', 'medium', 'high']
        result['reasoning_default'] = 'high'
        result['provider_hint'] = 'anthropic_adaptive'
        result['thinking_mode'] = 'adaptive'
        # No budget_tokens — effort controls depth
        result['supports_budget_tokens'] = False
    elif is_claude_4_6:
        # Both modes work; adaptive preferred, budget_tokens deprecated
        result['reasoning'] = True
        result['reasoning_levels'] = ['low', 'medium', 'high']
        result['reasoning_default'] = 'high'
        result['provider_hint'] = 'anthropic_adaptive'
        result['thinking_mode'] = 'adaptive'
        result['supports_budget_tokens'] = True  # still works but deprecated
    elif is_claude_4_5_or_earlier:
        # Extended thinking with budget_tokens (min 1024)
        result['reasoning'] = True
        # budget_tokens is a numeric value, not discrete levels
        result['reasoning_levels'] = ['enabled', 'disabled']
        result['reasoning_default'] = 'disabled'
        result['provider_hint'] = 'anthropic_budget'
        result['thinking_mode'] = 'enabled'
        result['supports_budget_tokens'] = True
        result['budget_tokens_min'] = 1024
    else:
        # Unknown model — assume no thinking
        result['reasoning'] = False
        result['reasoning_levels'] = []
        result['reasoning_default'] = None
        result['provider_hint'] = None
        result['thinking_mode'] = None
        result['supports_budget_tokens'] = False

    result['source'] = 'anthropic'

    # Optional: confirm connectivity with a minimal call
    try:
        from anthropic import Anthropic
        client = Anthropic(api_key=api_key, timeout=timeout)
        response = client.messages.create(
            model=model_name,
            max_tokens=16,
            messages=[{'role': 'user', 'content': 'Say "ok"'}],
        )
        result['confirmed'] = True
    except Exception as e:
        log.debug(f"Anthropic connectivity check failed for {model_name}: {e}")
        result['confirmed'] = False

    return result


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def discover_capabilities(
    model_provider: str,
    model_name: str,
    model_base_url: str,
    model_api_key: str,
    request_timeout: int = 60,
) -> Dict[str, Any]:
    """
    Discover model capabilities based on the configured provider.

    Args:
        model_provider: provider label (e.g. 'OpenAI', 'Local (Ollama)', 'Anthropic')
        model_name:     model identifier (e.g. 'gpt-4o', 'gpt-oss', 'claude-sonnet-4-6')
        model_base_url: base URL for the API endpoint
        model_api_key:  API key (required for OpenAI/Anthropic probes)
        request_timeout: timeout in seconds for probe calls

    Returns:
        Dict with discovered capabilities.
    """
    provider = model_provider.lower()
    base_url = (model_base_url or '').rstrip('/')

    # Route to the appropriate discovery strategy
    if 'ollama' in provider or 'local' in provider \
            or '11434' in base_url or 'localhost' in base_url or '127.0.0.1' in base_url:
        result = _discover_ollama(base_url, model_name)
    elif 'anthropic' in provider or 'claude' in model_name.lower():
        result = _discover_anthropic(model_name, model_api_key, min(request_timeout, 30))
    else:
        # Default: OpenAI-compatible
        result = _discover_openai_compatible(
            base_url, model_name, model_api_key, min(request_timeout, 30))

    result['discovered_at'] = datetime.now().isoformat()

    # Ensure all expected keys are present
    result.setdefault('reasoning', False)
    result.setdefault('reasoning_levels', [])
    result.setdefault('reasoning_default', None)
    result.setdefault('context_length', None)
    result.setdefault('vision', False)
    result.setdefault('tools', False)
    result.setdefault('model_details', {})
    result.setdefault('provider_hint', None)
    result.setdefault('source', 'unknown')

    return result
