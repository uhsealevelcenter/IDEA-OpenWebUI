# PaperQA Skill (Open Terminal)

This environment can answer questions about the user's scientific papers using
**PaperQA**, a high-accuracy RAG system that produces answers with in-text
citations and can extract figures/tables.

Use this skill whenever the user asks something about "my papers", "my
library", "the PDFs I uploaded", "the literature", a specific paper, or anything
that should be grounded in their documents. **Do not answer such questions from
your own memory** — run PaperQA so the answer is grounded and cited.

## Where papers live

All papers must be placed in:

```
~/papers
```

You can check what is currently there:

```bash
ls -la ~/papers
```

### Asking the user to add papers

If `~/papers` is empty (or missing the relevant paper), tell the user to add
their PDFs. In Open WebUI, the Open Terminal file-browser sidebar lets them
**drag and drop PDF files** directly into a folder. Instruct them to:

1. Open the Open Terminal file browser sidebar.
2. Navigate to the `papers` folder in their home directory (create it if needed).
3. Drag their PDF files into `papers`.

PaperQA also accepts `.txt`, `.md`, `.html`, `.docx`, `.xlsx`, `.pptx`, and
source-code files — but PDFs are the typical case.

If the folder does not exist yet, create it:

```bash
mkdir -p ~/papers
```

## How to query

The query script is baked into the image at `/opt/paperqa` and is shared by all
users (papers and results stay per-user under `~/papers`). Run it with the
user's question as a single quoted argument:

```bash
python /opt/paperqa/pqa_query.py "What does Figure 4 show in the OceanAI paper?"
```

The first run over a new set of papers will take longer because PaperQA parses
and embeds each document and builds an index. Subsequent runs reuse a cached
index and a pickled `Docs` object, so they are much faster. Progress logs are
written to stderr; the final answer is printed to stdout.

For machine-readable output (answer plus the list of saved figures), add
`--json`:

```bash
python /opt/paperqa/pqa_query.py --json "Summarize the methods section"
```

## Interpreting the output

- **stdout** contains the formatted answer, including in-text citations like
  `(Author2024 pages 1-2)`. Relay this answer to the user, preserving the
  citations.
- Any figures or tables relevant to the answer are saved as image files in:

  ```
  ~/papers/pqa_media
  ```

  The plain-text output lists their paths (with page numbers when known); the
  `--json` output includes them under the `images` key. Mention to the user that
  these figures were saved there and can be viewed in the Open Terminal file
  browser.

## Requirements / troubleshooting

- The `OPENAI_API_KEY` environment variable must be set (PaperQA uses OpenAI for
  the LLM and embeddings by default). If a query fails with an authentication
  error, tell the user the key is missing or invalid.
- If the script reports "No papers found", `~/papers` is empty — guide the user
  through adding PDFs (see above).
- If you change which papers are in `~/papers`, just run the query again; the
  index and Docs cache update automatically based on the set of files present.
