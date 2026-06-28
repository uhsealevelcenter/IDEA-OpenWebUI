"""
Single-user PaperQA settings for the Open Terminal environment.

This is a standalone port of the IDEA project's create_pqa_settings, with the
multi-tenant machinery removed. Paths are fixed relative to the terminal user's
home directory so the Open WebUI AI can simply run pqa_query.py without passing
any path arguments.

    papers      -> ~/papers
    index       -> ~/papers/index
    docs cache  -> ~/papers/.docs_cache
    media out   -> ~/papers/pqa_media

LLM/embedding configuration mirrors the IDEA settings and uses OpenAI via the
OPENAI_API_KEY environment variable.
"""

import os
from pathlib import Path
from typing import Optional, Union

from paperqa import Settings
from paperqa.prompts import (
    CONTEXT_INNER_PROMPT,
    CONTEXT_OUTER_PROMPT,
    citation_prompt,
    default_system_prompt,
    env_reset_prompt,
    env_system_prompt,
    qa_prompt,
    select_paper_prompt,
    structured_citation_prompt,
    summary_json_prompt,
    summary_prompt,
)
from paperqa.settings import (
    AgentSettings,
    AnswerSettings,
    IndexSettings,
    MultimodalOptions,
    ParsingSettings,
    PromptSettings,
)

# Use the pymupdf parser when available for better image/figure extraction.
try:
    from paperqa_pymupdf import parse_pdf_to_pages as pymupdf_parser

    PDF_PARSER = pymupdf_parser
except ImportError:
    PDF_PARSER = None  # Falls back to PaperQA's default parser.

# Fixed locations relative to the terminal user's home directory.
PAPERS_DIR = Path(os.getenv("PQA_PAPER_DIRECTORY", str(Path.home() / "papers")))
INDEX_DIR = Path(os.getenv("PQA_INDEX_DIRECTORY", str(PAPERS_DIR / "index")))
DOCS_CACHE_DIR = Path(
    os.getenv("PQA_DOCS_CACHE_DIRECTORY", str(PAPERS_DIR / ".docs_cache"))
)
MEDIA_DIR = Path(os.getenv("PQA_MEDIA_DIRECTORY", str(PAPERS_DIR / "pqa_media")))

# LLM model - prefixed with openai/ for LiteLLM provider routing.
DEFAULT_LLM = os.getenv("PQA_LLM", "openai/gpt-5.4-2026-03-05")
DEFAULT_EMBEDDING = os.getenv("PQA_EMBEDDING", "text-embedding-3-small")

# Custom summary prompt that emphasizes page numbers for figures/tables.
CUSTOM_SUMMARY_JSON_SYSTEM = (
    "Provide a summary of the relevant information"
    " that could help answer the question based on the excerpt."
    " Your summary, combined with many others,"
    " will be given to the model to generate an answer."
    " Respond with the following JSON format:"
    '\n\n{{\n  "summary": "...",\n  "relevance_score": 0-10,\n  "used_images": "..."\n}}'
    "\n\nwhere `summary` is relevant information from the text - {summary_length} words."
    " `relevance_score` is an integer 0-10 for the relevance of `summary` to the question."
    " `used_images` is a boolean flag indicating"
    " if any images present in a multimodal message were used,"
    " and if no images were present it should be false."
    "\n\nThe excerpt may or may not contain relevant information."
    " If not, leave `summary` empty, and make `relevance_score` be 0."
    "\n\n**IMPORTANT: When describing figures, tables, or images,"
    " always include the page number where they appear"
    " (e.g., 'Figure 2 on page 5 shows...'). This is critical for user reference.**"
)


def create_pqa_settings(
    paper_directory: Union[str, Path] = PAPERS_DIR,
    index_directory: Union[str, Path] = INDEX_DIR,
    llm: str = DEFAULT_LLM,
    summary_llm: Optional[str] = None,
    embedding: str = DEFAULT_EMBEDDING,
    verbosity: int = 1,
    manifest_file: Optional[Union[str, Path]] = None,
) -> Settings:
    """Create a fully configured single-user PaperQA Settings object."""
    paper_directory = Path(paper_directory)
    index_directory = Path(index_directory)
    if manifest_file is not None:
        manifest_file = Path(manifest_file)

    if summary_llm is None:
        summary_llm = llm

    parsing_kwargs = {
        "citation_prompt": citation_prompt,
        "structured_citation_prompt": structured_citation_prompt,
        # Extract images/tables but do not run a vision LLM to caption them.
        "multimodal": MultimodalOptions.ON_WITHOUT_ENRICHMENT,
        # Skip per-doc LLM metadata inference for speed/cost.
        "use_doc_details": False,
        "reader_config": {
            "chunk_chars": 5000,
            "overlap": 250,
            "full_page": True,
        },
    }

    if PDF_PARSER is not None:
        parsing_kwargs["parse_pdf"] = PDF_PARSER

    settings = Settings(
        llm=llm,
        llm_config={
            "model_list": [
                {
                    "model_name": llm,
                    "litellm_params": {
                        "model": llm,
                        "temperature": 1,  # Required for gpt-5+ models.
                        "max_tokens": 16384,
                    },
                }
            ],
        },
        summary_llm=summary_llm,
        embedding=embedding,
        embedding_config={},
        temperature=1,  # Required for gpt-5+ models.
        batch_size=1,
        verbosity=verbosity,
        manifest_file=manifest_file,
        paper_directory=paper_directory,
        index_directory=index_directory,
        answer=AnswerSettings(
            evidence_k=5,
            evidence_retrieval=True,
            evidence_summary_length="about 100 words",
            evidence_skip_summary=False,
            answer_max_sources=5,
            max_answer_attempts=None,
            answer_length="about 200 words, but can be longer",
            max_concurrent_requests=10,
        ),
        parsing=ParsingSettings(**parsing_kwargs),
        prompts=PromptSettings(
            summary=summary_prompt,
            qa=qa_prompt,
            select=select_paper_prompt,
            pre=None,
            post=None,
            system=default_system_prompt,
            use_json=True,
            summary_json=summary_json_prompt,
            summary_json_system=CUSTOM_SUMMARY_JSON_SYSTEM,
            context_outer=CONTEXT_OUTER_PROMPT,
            context_inner=CONTEXT_INNER_PROMPT,
        ),
        agent=AgentSettings(
            agent_llm=llm,
            agent_llm_config={
                "model_list": [
                    {
                        "model_name": llm,
                        "litellm_params": {
                            "model": llm,
                        },
                    }
                ],
            },
            agent_prompt=env_reset_prompt,
            agent_system_prompt=env_system_prompt,
            search_count=8,
            index=IndexSettings(
                paper_directory=paper_directory,
                index_directory=index_directory,
                use_absolute_paper_directory=False,
                sync_with_paper_directory=True,
                recurse_subdirectories=False,
            ),
        ),
    )

    return settings


def get_default_settings() -> Settings:
    """Convenience accessor for the default single-user settings."""
    return create_pqa_settings()
