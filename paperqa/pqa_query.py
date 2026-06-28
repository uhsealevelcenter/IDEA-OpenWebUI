#!/usr/bin/env python3
"""
Query the local PaperQA knowledge base from the command line.

This is a single-user, standalone port of the IDEA project's
query_knowledge_base function. It:

  1. Builds/reuses a persistent PaperQA index over ~/papers.
  2. Loads a pickled Docs object from disk when available (keyed by the set of
     indexed files), otherwise parses + embeds the papers and caches the result.
  3. Runs the query with docs.aquery() so media content is preserved.
  4. Extracts figures/tables from the answer contexts and saves them as images
     to ~/papers/pqa_media.

Usage:
    python ~/paperqa/pqa_query.py "What does Figure 4 show?"
    python ~/paperqa/pqa_query.py --json "Summarize the methods"

Requires the OPENAI_API_KEY environment variable to be set.
"""

import argparse
import asyncio
import base64
import hashlib
import json
import sys
import time
from pathlib import Path

import nest_asyncio

# Allow nested event loops (e.g. when invoked from environments that already
# have a running loop).
nest_asyncio.apply()

from paperqa import Docs
from paperqa.agents.search import get_directory_index

from pqa_settings import (
    DOCS_CACHE_DIR,
    MEDIA_DIR,
    PAPERS_DIR,
    create_pqa_settings,
)

_DOCS_PKL = DOCS_CACHE_DIR / "docs.pkl"
_DOCS_REVISION = DOCS_CACHE_DIR / "revision.txt"


def _log(msg: str) -> None:
    """Write progress to stderr so stdout stays clean for the answer."""
    print(msg, file=sys.stderr, flush=True)


def _compute_revision(index_files: dict) -> str:
    """Stable fingerprint from the set of indexed file names."""
    return hashlib.md5(str(sorted(index_files.keys())).encode()).hexdigest()


def _save_docs_to_disk(docs, revision: str) -> None:
    """Pickle a Docs object + revision for cross-invocation reuse."""
    import pickle

    DOCS_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    try:
        with open(_DOCS_PKL, "wb") as f:
            pickle.dump(docs, f, protocol=pickle.HIGHEST_PROTOCOL)
        _DOCS_REVISION.write_text(revision)
        _log("[PQA] Docs cache saved to disk.")
    except Exception as exc:
        _log(f"[PQA] Warning: failed to pickle Docs: {exc}")
        _DOCS_PKL.unlink(missing_ok=True)
        _DOCS_REVISION.unlink(missing_ok=True)


def _load_docs_from_disk(expected_revision: str):
    """Load a pickled Docs object if the revision matches, else None."""
    import pickle

    if not _DOCS_PKL.exists() or not _DOCS_REVISION.exists():
        return None
    if _DOCS_REVISION.read_text().strip() != expected_revision:
        return None
    try:
        with open(_DOCS_PKL, "rb") as f:
            return pickle.load(f)  # trusted internal cache
    except Exception as exc:
        _log(f"[PQA] Warning: failed to load Docs from disk: {exc}")
        _DOCS_PKL.unlink(missing_ok=True)
        _DOCS_REVISION.unlink(missing_ok=True)
        return None


def _save_base64_image(data_url: str, output_dir: Path, prefix: str = "kb_figure"):
    """Save a base64 data URL to an image file. Returns path or None."""
    try:
        if not data_url or not data_url.startswith("data:image"):
            return None

        header, b64_data = data_url.split(",", 1)
        mime_type = header.split(":")[1].split(";")[0]  # e.g. "image/png"

        ext_map = {
            "image/png": ".png",
            "image/jpeg": ".jpg",
            "image/jpg": ".jpg",
            "image/gif": ".gif",
            "image/webp": ".webp",
        }
        ext = ext_map.get(mime_type, ".png")

        content_hash = hashlib.md5(b64_data.encode()).hexdigest()[:12]
        filepath = output_dir / f"{prefix}_{content_hash}{ext}"

        if filepath.exists():
            return filepath

        output_dir.mkdir(parents=True, exist_ok=True)
        filepath.write_bytes(base64.b64decode(b64_data))
        return filepath
    except Exception as exc:
        _log(f"[PQA] Warning: failed to save image: {exc}")
        return None


async def _build_index_and_docs(settings):
    """Build/reuse the search index and the (cached) Docs object.

    Returns (docs, n_files). docs is None when there are no papers yet.
    Shared by both the query path and the --prebuild path.
    """
    _log("[PQA] Building/loading index...")
    t_idx = time.perf_counter()
    index = await get_directory_index(settings=settings)
    _log(f"[PQA] Index loaded in {time.perf_counter() - t_idx:.2f}s.")

    index_files = await index.index_files
    if not index_files:
        return None, 0
    _log(f"[PQA] Found {len(index_files)} indexed file(s).")

    revision = _compute_revision(index_files)

    docs = _load_docs_from_disk(revision)
    if docs is not None:
        _log("[PQA] Loaded Docs from disk cache.")
    else:
        _log("[PQA] Building Docs object (no cache available)...")
        t_docs = time.perf_counter()
        docs = Docs()
        paper_directory = settings.agent.index.paper_directory
        for file_path in index_files.keys():
            full_path = paper_directory / file_path
            if full_path.exists():
                _log(f"[PQA]   Adding: {file_path}")
                await docs.aadd(full_path, settings=settings)
        _save_docs_to_disk(docs, revision)
        _log(f"[PQA] Docs built in {time.perf_counter() - t_docs:.2f}s.")

    return docs, len(index_files)


async def _prebuild_async() -> dict:
    """Parse + embed all papers and cache the Docs object, without querying.

    Intended to be fired after a new PDF is uploaded so the first real query
    is fast. Safe to run repeatedly: it short-circuits when the cache is fresh.
    """
    t_start = time.perf_counter()
    _log("[PQA] Prebuild: loading settings...")
    settings = create_pqa_settings()

    docs, n_files = await _build_index_and_docs(settings)
    if docs is None:
        msg = f"No papers found in {PAPERS_DIR}; nothing to prebuild."
        _log(f"[PQA] {msg}")
        return {"status": "empty", "message": msg, "indexed_files": 0}

    _log(f"[PQA] Prebuild complete in {time.perf_counter() - t_start:.2f}s.")
    return {"status": "ready", "indexed_files": n_files}


async def _query_async(query: str) -> dict:
    t_start = time.perf_counter()

    _log("[PQA] Step 1: Loading settings...")
    settings = create_pqa_settings()
    _log(f"[PQA] LLM: {settings.llm}, Embedding: {settings.embedding}")

    docs, _n_files = await _build_index_and_docs(settings)
    if docs is None:
        return {
            "answer": (
                f"No papers found in your knowledge base. "
                f"Please add PDFs to {PAPERS_DIR} first."
            ),
            "images": [],
        }

    _log(f"[PQA] Step 4: Querying: '{query}'...")
    t_query = time.perf_counter()
    session = await docs.aquery(query=query, settings=settings)
    _log(f"[PQA] Query complete in {time.perf_counter() - t_query:.2f}s.")

    _log("[PQA] Step 5: Extracting figures/tables from contexts...")
    saved_images = []
    seen_hashes = set()
    used_context_ids = getattr(session, "used_contexts", set())

    for context in session.contexts:
        is_used = context.id in used_context_ids if used_context_ids else True

        if not hasattr(context, "text") or not hasattr(context.text, "media"):
            continue

        for media in context.text.media:
            try:
                data_url = media.to_image_url()
                if not data_url:
                    continue

                if "," in data_url:
                    b64_part = data_url.split(",", 1)[1]
                    content_hash = hashlib.md5(b64_part.encode()).hexdigest()
                    if content_hash in seen_hashes:
                        continue
                    seen_hashes.add(content_hash)

                saved_path = _save_base64_image(data_url, MEDIA_DIR)
                if saved_path:
                    info = getattr(media, "info", {}) or {}
                    saved_images.append(
                        {
                            "path": str(saved_path),
                            "page": info.get("page_num", info.get("page")),
                            "type": info.get("type", "image"),
                            "description": info.get("enriched_description", ""),
                            "used_in_answer": is_used,
                            "chunk_name": getattr(context.text, "name", ""),
                        }
                    )
                    _log(f"[PQA] Saved: {saved_path.name}")
            except Exception as exc:
                _log(f"[PQA] Warning: failed to process media: {exc}")
                continue

    _log(f"[PQA] Extracted {len(saved_images)} unique image(s).")
    _log(f"[PQA] Total time: {time.perf_counter() - t_start:.2f}s")

    return {"answer": str(session), "images": saved_images}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Query the local PaperQA knowledge base (~/papers)."
    )
    parser.add_argument(
        "query",
        nargs="?",
        default=None,
        help="The question to ask about the papers. Omit when using --prebuild.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit the full result as JSON on stdout.",
    )
    parser.add_argument(
        "--prebuild",
        action="store_true",
        help="Build/refresh the index and Docs cache without querying, then exit.",
    )
    args = parser.parse_args()

    if not args.prebuild and not args.query:
        parser.error("a query is required unless --prebuild is given")

    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    if args.prebuild:
        result = loop.run_until_complete(_prebuild_async())
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(result.get("message", f"Prebuild {result.get('status')}: "
                                         f"{result.get('indexed_files', 0)} file(s) indexed"))
        return 0

    result = loop.run_until_complete(_query_async(args.query))

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(result["answer"])
        if result["images"]:
            print("\n--- Saved figures/tables ---")
            for img in result["images"]:
                page = img.get("page")
                page_str = f" (page {page})" if page is not None else ""
                print(f"- {img['path']}{page_str}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
