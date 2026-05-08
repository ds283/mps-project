#
# Created by David Seery on 07/05/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

import json
import time
import traceback

import requests
from billiard.exceptions import SoftTimeLimitExceeded
from flask import current_app

# ---------------------------------------------------------------------------
# Token estimation.
# ---------------------------------------------------------------------------

_TOKENS_PER_WORD = 1.6  # conservative for technical academic prose (equations, code, citations)

# ---------------------------------------------------------------------------
# Truncation constants.
# ---------------------------------------------------------------------------

_TRUNCATION_MARKER = "\n\n[... middle section omitted due to length ...]\n\n"
_MAX_WORDS_BEFORE_TRUNCATION = 12000
_TRUNCATION_HEAD_WORDS = 6000
_TRUNCATION_TAIL_WORDS = 6000

# ---------------------------------------------------------------------------
# LLM call constants.
# ---------------------------------------------------------------------------

_LLM_RETRY_ATTEMPTS = 3
_LLM_RETRY_DELAY = 5  # seconds


def _truncate_text(text: str) -> tuple[str, bool]:
    """
    If *text* exceeds _MAX_WORDS_BEFORE_TRUNCATION words, return a truncated
    version consisting of the first and last _TRUNCATION_{HEAD,TAIL}_WORDS words
    separated by a marker.  Returns (text, was_truncated).
    """
    words = text.split()
    if len(words) <= _MAX_WORDS_BEFORE_TRUNCATION:
        return text, False
    head = " ".join(words[:_TRUNCATION_HEAD_WORDS])
    tail = " ".join(words[-_TRUNCATION_TAIL_WORDS:])
    return head + _TRUNCATION_MARKER + tail, True


def _call_llm(
    base_url: str,
    model: str,
    system_prompt: str,
    user_prompt: str,
    schema: dict,
    options: dict | None = None,
    validate_fn=None,
    label: str = "llm",
) -> tuple[dict | None, str, Exception | None, int]:
    """
    Submit a prompt to Ollama via the OpenAI-compatible
    /v1/chat/completions endpoint with JSON-schema constrained generation.

    Returns (parsed_result, last_accumulated_text, last_exception, est_input_tokens).
    parsed_result is None if all attempts failed.
    est_input_tokens is a rough estimate of the input prompt size in tokens,
    useful for diagnosing context-window failures.
    """
    est_input_tokens = int(
        (len(system_prompt.split()) + len(user_prompt.split())) * _TOKENS_PER_WORD
    )
    accumulated = ""
    last_exc: Exception | None = None
    parsed_result: dict | None = None

    for attempt in range(_LLM_RETRY_ATTEMPTS):
        accumulated = ""
        try:
            resp = requests.post(
                f"{base_url}/v1/chat/completions",
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    "response_format": {
                        "type": "json_schema",
                        "json_schema": {
                            "name": "response",
                            "schema": schema,
                        },
                    },
                    "stream": True,
                    "temperature": 0.0,
                    "keep_alive": -1,
                    **({"options": options} if options else {}),
                },
                stream=True,
                timeout=(30, 3600),
            )
            resp.raise_for_status()

            finish_reason: str | None = None
            usage: dict | None = None
            seen_done = False
            for line in resp.iter_lines():
                if not line:
                    continue
                line_str = line.decode() if isinstance(line, bytes) else line
                if not isinstance(line_str, str) or not line_str.startswith("data: "):
                    continue
                payload = line_str[6:]
                if payload.strip() == "[DONE]":
                    seen_done = True
                    break
                try:
                    chunk_data = json.loads(payload)
                except (json.JSONDecodeError, ValueError):
                    continue
                if not isinstance(chunk_data, dict):
                    continue
                # Guard against null/empty choices (e.g. Ollama usage-only final chunk).
                choices = chunk_data.get("choices") or [{}]
                first_choice = choices[0] if choices and isinstance(choices[0], dict) else {}
                delta = first_choice.get("delta") or {}
                content = delta.get("content") if isinstance(delta, dict) else None
                if isinstance(content, str):
                    accumulated += content
                fr = first_choice.get("finish_reason")
                if fr is not None:
                    finish_reason = fr
                if chunk_data.get("usage"):
                    usage = chunk_data["usage"]

            if usage is not None:
                current_app.logger.debug(
                    f"{label}: token usage — prompt={usage.get('prompt_tokens')} "
                    f"completion={usage.get('completion_tokens')} "
                    f"total={usage.get('total_tokens')}"
                )
            if not seen_done:
                current_app.logger.warning(
                    f"{label}: stream ended without [DONE] marker on attempt {attempt + 1}; "
                    f"accumulated_len={len(accumulated)} finish_reason={finish_reason!r}"
                )
            if finish_reason == "length":
                raise ValueError(
                    f"output truncated by context window (finish_reason=length); "
                    f"prompt_tokens={usage.get('prompt_tokens') if usage else 'unknown'} "
                    f"completion_tokens={usage.get('completion_tokens') if usage else 'unknown'}"
                )

            parsed = json.loads(accumulated)
            if validate_fn is not None and not validate_fn(parsed):
                raise ValueError(
                    f"LLM response missing required keys; got: {list(parsed.keys())}"
                )
            parsed_result = parsed
            last_exc = None
            break

        except requests.HTTPError as exc:
            last_exc = exc
            status = exc.response.status_code if exc.response is not None else 0
            if 400 <= status < 500:
                current_app.logger.error(
                    f"{label}: permanent HTTP {status} error (~{est_input_tokens} est. input tokens): {exc}"
                )
                break
            current_app.logger.warning(
                f"{label}: transient HTTP error on attempt {attempt + 1} (~{est_input_tokens} est. input tokens): {exc}"
            )
            if attempt < _LLM_RETRY_ATTEMPTS - 1:
                time.sleep(_LLM_RETRY_DELAY)

        except SoftTimeLimitExceeded:
            raise  # must not be swallowed — propagate so the task fails cleanly

        except (json.JSONDecodeError, ValueError) as exc:
            last_exc = exc
            _tail = accumulated[-300:] if len(accumulated) > 300 else accumulated
            _usage_str = (
                f" prompt_tokens={usage.get('prompt_tokens')} completion_tokens={usage.get('completion_tokens')}"
                if usage else ""
            )
            current_app.logger.warning(
                f"{label}: JSON parse failure on attempt {attempt + 1} "
                f"(~{est_input_tokens} est. input tokens): {exc}\n"
                f"  seen_done={seen_done} finish_reason={finish_reason!r} "
                f"accumulated_len={len(accumulated)}{_usage_str}\n"
                f"  accumulated_tail: {_tail!r}"
            )
            if attempt < _LLM_RETRY_ATTEMPTS - 1:
                time.sleep(_LLM_RETRY_DELAY)

        except Exception as exc:
            last_exc = exc
            current_app.logger.warning(
                f"{label}: transient [{type(exc).__name__}] error on attempt {attempt + 1} "
                f"(~{est_input_tokens} est. input tokens): {exc}"
            )
            current_app.logger.warning(
                f"{label}: traceback (attempt {attempt + 1}):\n{traceback.format_exc()}"
            )
            if attempt < _LLM_RETRY_ATTEMPTS - 1:
                time.sleep(_LLM_RETRY_DELAY)

    return parsed_result, accumulated, last_exc, est_input_tokens
