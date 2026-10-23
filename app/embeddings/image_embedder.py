"""
app/embeddings/image_embedder.py
---------------------------------
Image and cross-modal text embedding for OmniLens using ``open_clip``.

Model: ``ViT-B-32`` with pretrained weights ``openai``
  - Output dimension: **512** (for both image and text encoders)
  - Smallest standard CLIP checkpoint — good CPU speed, ~340 MB on disk.
  - First load downloads weights from HuggingFace Hub (cached in
    ``~/.cache/huggingface/`` on subsequent calls).

Design decision — TWO separate embedding spaces
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
OmniLens uses **two distinct embedding spaces**, not one joint space:

  1. **Text chunks** (PDF page text) → ``all-MiniLM-L6-v2`` (384-dim)
     stored in ChromaDB collection ``"text_chunks"``

  2. **Image chunks** (embedded PDF images, standalone uploads) → CLIP image
     encoder (512-dim) stored in ChromaDB collection ``"image_chunks"``

At query time a user question gets embedded **twice**:
  - Once with sentence-transformers → searches ``"text_chunks"``
  - Once with CLIP's **text encoder** (this module's :func:`embed_clip_text`)
    → searches ``"image_chunks"``

Why two spaces instead of one joint space?
  - CLIP's image and text encoders share a latent space by design, so a CLIP
    text query can retrieve CLIP-embedded images natively.
  - sentence-transformers is significantly better than CLIP's text encoder at
    dense text retrieval (it was fine-tuned on NLI/STS tasks).
  - Trying to force both text and image chunks into one CLIP space means using
    CLIP's weaker text encoder for all text retrieval — a quality regression.
  - This two-collection approach is simpler, more debuggable, and performs
    better on CPU without any special alignment training.

Module-level singleton
~~~~~~~~~~~~~~~~~~~~~~~
Both the CLIP model and the image preprocessing transform are loaded ONCE when
this module is first imported.  Never reload them per-request.
"""

import time
from pathlib import Path
from typing import Union

import open_clip
import torch
from PIL import Image

from app.cache.cache_manager import (
    get_cached_embedding,
    hash_content,
    set_cached_embedding,
)
from app.utils.logging_config import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Model constants
# ---------------------------------------------------------------------------

CLIP_MODEL_NAME = "ViT-B-32"
CLIP_PRETRAINED = "openai"

#: Output embedding dimension for ViT-B-32 (both image and text encoders).
EMBEDDING_DIM = 512

# ---------------------------------------------------------------------------
# Module-level singleton — loaded exactly once
# ---------------------------------------------------------------------------

_t_load_start = time.perf_counter()
logger.info(
    "Loading CLIP model '%s' (pretrained='%s')…",
    CLIP_MODEL_NAME,
    CLIP_PRETRAINED,
)

_clip_model, _, _clip_preprocess = open_clip.create_model_and_transforms(
    CLIP_MODEL_NAME,
    pretrained=CLIP_PRETRAINED,
)
_clip_model.eval()  # inference mode — disables dropout etc.

# CLIP's own tokeniser for the text encoder
_clip_tokenizer = open_clip.get_tokenizer(CLIP_MODEL_NAME)

_load_elapsed = time.perf_counter() - _t_load_start
logger.info(
    "CLIP model '%s/%s' loaded in %.2fs (dim=%d)",
    CLIP_MODEL_NAME,
    CLIP_PRETRAINED,
    _load_elapsed,
    EMBEDDING_DIM,
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def embed_image(image_path: Union[str, Path]) -> list[float]:
    """Encode an image file through CLIP's image encoder.

    The result is an L2-normalised 512-dim vector that lives in the same
    latent space as :func:`embed_clip_text` — enabling cross-modal search.
    Results are cached by image file byte content hash to prevent redundant
    embedding on re-upload.

    Args:
        image_path: Absolute (or repo-relative) path to a JPEG/PNG image.

    Returns:
        A list of 512 floats.

    Raises:
        FileNotFoundError: If *image_path* does not exist.
        OSError: If the file cannot be opened as an image (e.g., corrupt file).
    """
    image_path = Path(image_path)
    if not image_path.exists():
        raise FileNotFoundError(f"Image not found: {image_path}")

    try:
        content_hash = hash_content(image_path.read_bytes())
        cached = get_cached_embedding(content_hash)
        if cached is not None:
            return cached
    except Exception as exc:
        logger.warning("Embedding cache check failed for image %s: %s", image_path, exc)
        content_hash = None

    pil_image = Image.open(image_path).convert("RGB")
    tensor = _clip_preprocess(pil_image).unsqueeze(0)  # (1, C, H, W)

    with torch.no_grad():
        features = _clip_model.encode_image(tensor)
        features = features / features.norm(dim=-1, keepdim=True)  # L2 normalise

    result = features.squeeze(0).cpu().tolist()
    if content_hash:
        set_cached_embedding(content_hash, result)
    return result


def embed_clip_text(text: str) -> list[float]:
    """Encode a text string through CLIP's text encoder.

    Use this to embed a **search query** when searching the ``"image_chunks"``
    collection — the resulting vector lives in the same space as
    :func:`embed_image` vectors.
    Results are cached by query string hash to avoid re-embedding repeated queries.

    Do NOT use this for embedding PDF text chunks; use
    ``app.embeddings.text_embedder.embed_text`` for that.

    Args:
        text: The query or caption text to embed.

    Returns:
        A list of 512 floats, L2-normalised.
    """
    content_hash = hash_content(f"clip_text:{text}")
    cached = get_cached_embedding(content_hash)
    if cached is not None:
        return cached

    tokens = _clip_tokenizer([text])  # shape: (1, context_length)

    with torch.no_grad():
        features = _clip_model.encode_text(tokens)
        features = features / features.norm(dim=-1, keepdim=True)  # L2 normalise

    result = features.squeeze(0).cpu().tolist()
    set_cached_embedding(content_hash, result)
    return result
