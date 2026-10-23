"""
app/generation/answer_generator.py
------------------------------------
Grounded answer generation using the Groq API with streaming,
general-knowledge fallback, and follow-up query rewriting.

Key design decisions
~~~~~~~~~~~~~~~~~~~~~
1. **Strict grounding prompt**: Instructs the model to answer ONLY from the
   provided chunks. If the chunks lack the answer, the model must output
   EXACTLY the sentinel token NOT_IN_DOCUMENTS and nothing else.
2. **General-knowledge fallback**: When NOT_IN_DOCUMENTS is detected and general
   knowledge is enabled, a secondary Groq call generates a concise answer
   without document chunks.
3. **Follow-up question rewriting**: If conversation history is present, rewrites
   the query into a standalone question using GROQ_REWRITE_MODEL.
4. **Streaming answers**: Emits tokens in real-time while buffering initial chars
   to catch the NOT_IN_DOCUMENTS sentinel, strips citation tags from streamed text,
   and ignores reasoning model thoughts.
5. **Reasoning model resilience**: Retries once with higher token limit if content
   is empty, never exposing internal reasoning to users.
"""

from __future__ import annotations

import logging
import os
import re
import time
from typing import Any, Generator, Optional

from dotenv import load_dotenv
from groq import Groq
from groq import APIStatusError, APIConnectionError, APITimeoutError

load_dotenv()

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Model Configuration & Constants
# ---------------------------------------------------------------------------

_DEFAULT_MODEL = "llama3-70b-8192"
_DEFAULT_REWRITE_MODEL = "openai/gpt-oss-20b"
_MAX_TOKENS = 1024
_TEMPERATURE = 0.1
_REQUEST_TIMEOUT = 25

NOT_IN_DOCUMENTS_TOKEN = "NOT_IN_DOCUMENTS"

# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

_SYSTEM_PREAMBLE = """\
You are a precise, evidence-grounded question-answering assistant.
You will be given a user question and a numbered list of source chunks
(excerpts from PDFs and images). Your task is to answer the question
STRICTLY using only the information in those chunks.

Rules you MUST follow:
1. Answer only from the provided chunks — do NOT use prior knowledge or
   information that is not present in the chunks below.
2. If the chunks do not contain enough information to answer the question,
   respond EXACTLY with the token: NOT_IN_DOCUMENTS
   Do not provide any other words, reasoning, apology, or explanation if the
   information is not present in the chunks. Output only NOT_IN_DOCUMENTS.
3. For EVERY factual claim in your answer, cite the chunk(s) you used.
   Use the format [CHUNK:<chunk_id>] or [PAGE:<page_number>] or
   [IMAGE:<source_filename>] immediately after the claim.
   Example of correct citation: "Revenue was $48M [CHUNK:chunk-fin-p2]."
4. Do NOT fabricate page numbers, chunk IDs, or source filenames.
5. Be concise but complete — do not pad the answer with unrelated information.
"""

_CHUNK_HEADER = "--- SOURCE CHUNKS ---"
_QUESTION_HEADER = "--- QUESTION ---"
_INSTRUCTION_FOOTER = """\
--- END OF SOURCES ---
Now answer the question above, following all the rules in the preamble.
Cite every factual claim with [CHUNK:<id>], [PAGE:<n>], or [IMAGE:<filename>].
Example of a correct citation: "The margin was 32% [CHUNK:chunk-fin-p2]."
If you cannot answer strictly from the sources, respond EXACTLY with: NOT_IN_DOCUMENTS
"""

_GENERAL_KNOWLEDGE_PREAMBLE = """\
You are a helpful, concise AI assistant.
Answer the user's question concisely and accurately based on general knowledge.
If you are unsure or do not know the answer, state that clearly.
Do NOT fabricate citations, and do not reference any document chunk IDs or page numbers.
"""

_REWRITE_SYSTEM_PROMPT = """\
You are a search query rewriting specialist.
Given the recent conversation history and a follow-up question from the user,
rewrite the follow-up question into a complete, standalone search query that can
be understood without the conversation history.

Rules:
1. Preserve specific entities, filenames, and technical terms exactly as they appear.
2. If the question is already fully standalone, return it unchanged.
3. Return ONLY the standalone rewritten question — do not add explanations, quotes, or notes.
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _format_chunk_for_prompt(idx: int, chunk: dict[str, Any]) -> str:
    """Render a single chunk as a numbered block for the Groq prompt."""
    meta: dict[str, Any] = chunk.get("metadata", {})
    chunk_id: str = chunk.get("chunk_id", "unknown")
    chunk_type: str = meta.get("chunk_type", "text")
    source_filename: str = meta.get("source_filename", "unknown")
    page_num: Any = meta.get("page_number")
    rerank_score: float = chunk.get("rerank_score", 0.0)

    lines: list[str] = [
        f"[CHUNK {idx}]",
        f"  chunk_id: {chunk_id}",
        f"  source: {source_filename}",
    ]
    if page_num not in (None, "", -1):
        lines.append(f"  page: {page_num}")
    lines.append(f"  type: {chunk_type}")
    lines.append(f"  relevance_score: {rerank_score:.3f}")

    if chunk_type == "text":
        content_text = (
            chunk.get("content_text")
            or meta.get("content_text", "")
        ).strip()
        lines.append(f"  content:\n    {content_text}")
    else:
        ocr = meta.get("ocr_text", "").strip()
        objects = meta.get("detected_objects", "").strip()
        caption = meta.get("caption", "").strip()
        img_path = chunk.get("content_image_path") or meta.get("content_image_path", "")

        lines.append("  [IMAGE CHUNK — pixel data not included in prompt]")
        if img_path:
            lines.append(f"  image_file: {img_path}")
        if ocr:
            lines.append(f"  ocr_text:\n    {ocr}")
        if objects:
            lines.append(f"  detected_objects: {objects}")
        if caption:
            lines.append(f"  caption: {caption}")
        if not (ocr or objects or caption):
            lines.append("  (no text extracted from this image)")

    return "\n".join(lines)


def _build_prompt(question: str, chunks: list[dict[str, Any]]) -> str:
    """Assemble the full user message string for the Groq chat call."""
    chunk_blocks = "\n\n".join(
        _format_chunk_for_prompt(i + 1, c) for i, c in enumerate(chunks)
    )
    return (
        f"{_CHUNK_HEADER}\n\n"
        f"{chunk_blocks}\n\n"
        f"{_INSTRUCTION_FOOTER}\n\n"
        f"{_QUESTION_HEADER}\n{question}\n"
    )


def _parse_cited_chunk_ids(response_text: str, chunks: list[dict[str, Any]]) -> list[str]:
    """Extract chunk_ids cited in response_text."""
    found_ids: set[str] = set()

    for m in re.finditer(r"\[CHUNK:([^\]]+)\]", response_text):
        found_ids.add(m.group(1).strip())

    page_to_ids: dict[str, list[str]] = {}
    for c in chunks:
        meta = c.get("metadata", {})
        pn = meta.get("page_number")
        if pn not in (None, "", -1):
            page_to_ids.setdefault(str(pn), []).append(c.get("chunk_id", ""))
    for m in re.finditer(r"\[PAGE:(\d+)\]", response_text):
        page_str = m.group(1)
        found_ids.update(page_to_ids.get(page_str, []))

    fn_to_ids: dict[str, list[str]] = {}
    for c in chunks:
        meta = c.get("metadata", {})
        fn = meta.get("source_filename", "")
        if fn:
            fn_to_ids.setdefault(fn, []).append(c.get("chunk_id", ""))
    for m in re.finditer(r"\[IMAGE:([^\]]+)\]", response_text):
        fn = m.group(1).strip()
        found_ids.update(fn_to_ids.get(fn, []))

    if not found_ids:
        logger.warning(
            "Groq response contains no citations. Falling back to all %d passed chunks.",
            len(chunks),
        )
        return [c.get("chunk_id", "") for c in chunks]

    return sorted(found_ids)


def _get_client() -> tuple[Groq, str]:
    """Retrieve configured Groq client and model name, or raise ValueError."""
    api_key = os.environ.get("GROQ_API_KEY", "").strip()
    if not api_key:
        raise ValueError(
            "GROQ_API_KEY is not set. "
            "Get a free key at https://console.groq.com/keys "
            "and add it to your .env file as GROQ_API_KEY=<your_key>."
        )
    model = os.environ.get("GROQ_MODEL", "").strip() or _DEFAULT_MODEL
    return Groq(api_key=api_key, timeout=_REQUEST_TIMEOUT), model


def _get_retry_after(exc: APIStatusError) -> Optional[int]:
    """Read the Retry-After header from a 429 response."""
    try:
        headers = exc.response.headers  # type: ignore[attr-defined]
        val = headers.get("retry-after") or headers.get("x-ratelimit-reset-requests")
        if val is not None:
            return max(1, int(float(val)))
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Question Rewriting
# ---------------------------------------------------------------------------

def rewrite_question(question: str, history: list[dict[str, str]]) -> str:
    """Rewrite a follow-up question into a standalone question using conversation history.

    Args:
        question: The user's new question.
        history: Up to 3 recent turns as [{"question": ..., "answer": ...}].

    Returns:
        The rewritten standalone question, or original question if history is empty
        or if rewrite fails.
    """
    if not history:
        return question

    rewrite_model = (
        os.environ.get("GROQ_REWRITE_MODEL", "").strip() or _DEFAULT_REWRITE_MODEL
    )
    api_key = os.environ.get("GROQ_API_KEY", "").strip()
    if not api_key:
        return question

    try:
        client = Groq(api_key=api_key, timeout=10)
        recent_turns = history[-3:]
        history_lines: list[str] = []
        for i, turn in enumerate(recent_turns, 1):
            q_txt = turn.get("question", "").strip()
            a_txt = turn.get("answer", "").strip()[:400]
            history_lines.append(f"Turn {i}:\nUser: {q_txt}\nAssistant: {a_txt}")

        history_block = "\n\n".join(history_lines)
        user_content = (
            f"Conversation History:\n{history_block}\n\n"
            f"Follow-up question:\n{question}\n\n"
            "Standalone rewritten question:"
        )

        resp = client.chat.completions.create(
            model=rewrite_model,
            messages=[
                {"role": "system", "content": _REWRITE_SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            temperature=0.0,
            max_tokens=256,
        )
        content = (resp.choices[0].message.content or "").strip()
        # Clean quotes
        if content.startswith('"') and content.endswith('"'):
            content = content[1:-1].strip()

        if content:
            logger.info("Rewrote question '%s' -> '%s' using %s", question, content, rewrite_model)
            return content
        return question
    except Exception as exc:
        logger.warning("Query rewrite failed, falling back to original: %s", exc)
        return question


# ---------------------------------------------------------------------------
# Grounded Generation (Non-Streaming)
# ---------------------------------------------------------------------------

def generate_answer(
    question: str,
    reranked_chunks: list[dict[str, Any]],
) -> dict[str, Any]:
    """Generate a grounded answer using the Groq API.

    Returns:
        Dict with keys:
          - answer (str)
          - cited_chunks (list[str])
          - raw_chunks_used (list[dict])
          - model_used (str)
    """
    client, model = _get_client()

    user_message = _build_prompt(question, reranked_chunks)
    messages = [
        {"role": "system", "content": _SYSTEM_PREAMBLE},
        {"role": "user", "content": user_message},
    ]

    answer_text = ""
    max_attempts = 3
    current_max_tokens = _MAX_TOKENS

    for attempt in range(max_attempts):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=_TEMPERATURE,
                max_tokens=current_max_tokens,
            )
            choice = response.choices[0]
            answer_text = (choice.message.content or "").strip()

            # Handle reasoning model quirk: empty content
            if not answer_text and attempt < max_attempts - 1:
                logger.warning(
                    "Groq returned empty content (reasoning quirk). Retrying with max_tokens=4096..."
                )
                current_max_tokens = 4096
                time.sleep(1)
                continue

            break

        except APIStatusError as exc:
            status = exc.status_code
            if status == 429 and attempt < max_attempts - 1:
                wait_sec = _get_retry_after(exc) or (attempt + 1) * 3
                logger.warning("Groq rate limit (attempt %d). Waiting %ds...", attempt + 1, wait_sec)
                time.sleep(wait_sec)
                continue
            raise exc

        except (APIConnectionError, APITimeoutError) as exc:
            if attempt < max_attempts - 1:
                time.sleep(2)
                continue
            raise exc

    # Sentinel detection
    if NOT_IN_DOCUMENTS_TOKEN in answer_text:
        return {
            "answer": NOT_IN_DOCUMENTS_TOKEN,
            "cited_chunks": [],
            "raw_chunks_used": reranked_chunks,
            "model_used": model,
        }

    cited_ids = _parse_cited_chunk_ids(answer_text, reranked_chunks)

    return {
        "answer": answer_text,
        "cited_chunks": cited_ids,
        "raw_chunks_used": reranked_chunks,
        "model_used": model,
    }


# ---------------------------------------------------------------------------
# General Knowledge Generation (Non-Streaming)
# ---------------------------------------------------------------------------

def generate_general_knowledge_answer(question: str) -> dict[str, Any]:
    """Generate a concise answer from general knowledge with no document citations."""
    client, model = _get_client()

    messages = [
        {"role": "system", "content": _GENERAL_KNOWLEDGE_PREAMBLE},
        {"role": "user", "content": question},
    ]

    response = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=0.2,
        max_tokens=512,
    )
    answer_text = (response.choices[0].message.content or "").strip()
    return {
        "answer": answer_text,
        "model_used": model,
    }


# ---------------------------------------------------------------------------
# Streaming Grounded Generation
# ---------------------------------------------------------------------------

def _strip_citation_tag_stream(
    token_stream: Generator[str, None, None]
) -> Generator[tuple[str, list[str]], None, None]:
    """Generator filter that strips [CHUNK:...], [PAGE:...], [IMAGE:...] tags
    from incoming token deltas and yields (clean_text_delta, [found_tag_strings]).
    """
    buffer = ""
    inside_tag = False

    for chunk in token_stream:
        buffer += chunk
        while True:
            if not inside_tag:
                bracket_pos = buffer.find("[")
                if bracket_pos == -1:
                    # No tag start: yield everything except last character if it could be start
                    if buffer:
                        yield buffer, []
                        buffer = ""
                    break
                else:
                    # Yield text before the bracket
                    if bracket_pos > 0:
                        yield buffer[:bracket_pos], []
                        buffer = buffer[bracket_pos:]
                    inside_tag = True
            else:
                closing_pos = buffer.find("]")
                if closing_pos == -1:
                    # Incomplete tag. If buffer gets too long without closing bracket, not a citation
                    if len(buffer) > 80:
                        yield buffer, []
                        buffer = ""
                        inside_tag = False
                    break
                else:
                    tag_str = buffer[: closing_pos + 1]
                    buffer = buffer[closing_pos + 1 :]
                    inside_tag = False

                    if re.match(r"^\[(CHUNK|PAGE|IMAGE):[^\]]+\]$", tag_str):
                        # Citation tag: strip it, but record it
                        yield "", [tag_str]
                    else:
                        # Other bracketed text: preserve it
                        yield tag_str, []

    if buffer:
        yield buffer, []


def stream_grounded_answer(
    question: str,
    reranked_chunks: list[dict[str, Any]],
) -> Generator[dict[str, Any], None, None]:
    """Stream grounded answer generation with sentinel buffering and citation stripping.

    Yields event dicts:
      - {"type": "sentinel", "sentinel": "NOT_IN_DOCUMENTS", "model_used": str}
      - {"type": "token", "text": str}
      - {"type": "complete", "answer": str, "cited_chunks": list[str], "model_used": str}
    """
    client, model = _get_client()
    user_message = _build_prompt(question, reranked_chunks)
    messages = [
        {"role": "system", "content": _SYSTEM_PREAMBLE},
        {"role": "user", "content": user_message},
    ]

    response_stream = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=_TEMPERATURE,
        max_tokens=_MAX_TOKENS,
        stream=True,
    )

    # Helper raw delta generator ignoring reasoning tokens
    def _raw_deltas():
        for chunk in response_stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            # Ignore reasoning field entirely
            text = getattr(delta, "content", None) or ""
            if text:
                yield text

    # Buffer the first ~25 characters to catch NOT_IN_DOCUMENTS without leaking
    sentinel_buffer = ""
    raw_gen = _raw_deltas()

    while len(sentinel_buffer) < 25:
        try:
            delta = next(raw_gen)
            sentinel_buffer += delta
        except StopIteration:
            break

    if NOT_IN_DOCUMENTS_TOKEN in sentinel_buffer:
        yield {
            "type": "sentinel",
            "sentinel": NOT_IN_DOCUMENTS_TOKEN,
            "model_used": model,
        }
        return

    # If not sentinel, process sentinel_buffer and remaining deltas through citation stripper
    def _combined_deltas():
        if sentinel_buffer:
            yield sentinel_buffer
        yield from raw_gen

    accumulated_clean_answer: list[str] = []
    collected_tags: list[str] = []

    for clean_text, tags in _strip_citation_tag_stream(_combined_deltas()):
        collected_tags.extend(tags)
        if clean_text:
            accumulated_clean_answer.append(clean_text)
            yield {"type": "token", "text": clean_text}

    full_answer_text = "".join(accumulated_clean_answer).strip()

    # Parse cited chunk IDs from collected tags plus text
    tag_blob = full_answer_text + " " + " ".join(collected_tags)
    cited_ids = _parse_cited_chunk_ids(tag_blob, reranked_chunks)

    yield {
        "type": "complete",
        "answer": full_answer_text,
        "cited_chunks": cited_ids,
        "model_used": model,
    }


def stream_general_knowledge_answer(
    question: str,
) -> Generator[dict[str, Any], None, None]:
    """Stream general knowledge fallback generation.

    Yields:
      - {"type": "token", "text": str}
      - {"type": "complete", "answer": str, "model_used": str}
    """
    client, model = _get_client()
    messages = [
        {"role": "system", "content": _GENERAL_KNOWLEDGE_PREAMBLE},
        {"role": "user", "content": question},
    ]

    response_stream = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=0.2,
        max_tokens=512,
        stream=True,
    )

    accumulated: list[str] = []
    for chunk in response_stream:
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta
        text = getattr(delta, "content", None) or ""
        if text:
            accumulated.append(text)
            yield {"type": "token", "text": text}

    yield {
        "type": "complete",
        "answer": "".join(accumulated).strip(),
        "model_used": model,
    }
