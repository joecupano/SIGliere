# Building a Local RAG Knowledge Base — Antenna Design Example

A hands-on guide to building a local, sovereign RAG (retrieval-augmented
generation) knowledge base using this build's existing AI stack — no
cloud dependency, no data leaving the box. We'll use a real, substantial
public source (L.B. Cebik W4RNL's antenna design collection) as the
worked example, and end with a live chat session querying it.

## What You're Building

RAG lets a local LLM answer questions grounded in specific source
material it wasn't trained on — instead of relying purely on what
`qwen3:14b` already knows (or doesn't), it retrieves relevant passages
from your own document collection and answers from those, with the
source material never leaving this machine. Same "local by default"
philosophy as the rest of this build.

## About the Source Material

[antenna2/cebik](https://github.com/antenna2/cebik) is a community-preserved
archive of L.B. Cebik's (W4RNL, silent key 2008) antenna design writings —
books, decades of magazine columns, and detailed antenna modeling notes
(NEC-2/NEC-4). Cebik was one of the most respected technical writers in
amateur radio antenna theory; this collection is a genuinely valuable,
substantial technical corpus — hundreds of real pages, not a toy dataset.

**Licensing, stated plainly rather than skipped past:** this is
copyrighted material. The source explicitly states it "may be used for
personal purposes, but may not be reproduced for publication in print or
any other medium without permission," and may not be used commercially.
That fits exactly what this guide does — a private, local knowledge base
for your own use, never redistributed or made public — but it's worth
being direct about: don't repurpose the resulting processed corpus for
any public-facing or commercial system.

## Architecture Note: Two Ingest Paths, and Why We're Using One Specifically

This build already has a standalone document ingest pipeline
(`ai-ingest/`; see `scripts/install-ai-ingest.sh`) — but it's deliberately
**decoupled from Open WebUI's own chat RAG**, by design. AI ingest's
output lands in `/data/corpus/processed` as a standalone corpus; nothing
currently wires it into a chat-queryable retrieval layer.

For a chat session that retrieves from this material, use **Open WebUI native
Knowledge**. It provides embedding and retrieval already wired into chat. By
default Open WebUI embeds with a built-in CPU model
(`sentence-transformers/all-MiniLM-L6-v2`), but this build sets embeddings to
**`nomic-embed-text` through Ollama** (pulled by `install-ollama.sh`), reached
over Caddy's private `/ollama` route, so retrieval makes no network calls
outside the host. If you also want this material in the standalone
pipeline corpus, that is an independent, optional step and is not required for
the chat session below.

## Step 1: Get the Source Material

```
mkdir -p ~/rag-demo
cd ~/rag-demo
git clone --depth 1 https://github.com/antenna2/cebik.git
```

`--depth 1` skips the full commit history — you only need the current
files, and this repo has been maintained for a while.

## Step 2: Convert HTML to Clean Text

Open WebUI's document upload works best with clean text/markdown, not
raw HTML with 1990s-era markup (the source material itself notes much
of it predates modern HTML standards). Rather than introduce a new
dependency, this reuses **Docling — already installed in the AI ingest
`ai-ingest` venv** — the same conversion engine this build already
relies on elsewhere, applied here as a one-off preprocessing pass
rather than through the full `ingest.py` pipeline.

**Prerequisite:** that venv only exists once the AI ingest capability is
installed (`./scripts/install-ai-ingest.sh`; see [INSTALL.md](../INSTALL.md)
section 8). It is not part of the core install, so check that
`${HOME}/.local/share/sigliere/venvs/ai-ingest/bin/python3` exists before
Step 2, and run the installer if it does not.

Save this as `~/rag-demo/convert.py`:

```python
#!/usr/bin/env python3
"""One-off HTML -> Markdown conversion for RAG prep, using Docling
directly (not the full `ingest.py` pipeline — this is a
standalone preprocessing step feeding Open WebUI's Knowledge feature,
not this project's own /data/corpus)."""

import sys
from pathlib import Path
from docling.document_converter import DocumentConverter

SOURCE_DIR = Path.home() / "rag-demo" / "cebik"
OUTPUT_DIR = Path.home() / "rag-demo" / "converted"

def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    converter = DocumentConverter()

    html_files = list(SOURCE_DIR.rglob("*.html"))
    print(f"Found {len(html_files)} HTML files.")

    converted, failed = 0, 0
    for html_file in html_files:
        try:
            result = converter.convert(str(html_file))
            markdown = result.document.export_to_markdown()

            # Flatten into one directory, encoding the relative path in
            # the filename so hundreds of similarly-named pages
            # (common across the columns/books directories) don't collide.
            rel_path = html_file.relative_to(SOURCE_DIR)
            safe_name = str(rel_path.with_suffix(".md")).replace("/", "__")
            out_path = OUTPUT_DIR / safe_name
            out_path.write_text(markdown, encoding="utf-8")
            converted += 1
        except Exception as exc:
            print(f"  FAILED: {html_file} — {exc}", file=sys.stderr)
            failed += 1

    print(f"Converted: {converted}, Failed: {failed}")
    print(f"Output: {OUTPUT_DIR}")

if __name__ == "__main__":
    main()
```

Run it with the AI ingest environment's Python — no separate install needed:

```
${HOME}/.local/share/sigliere/venvs/ai-ingest/bin/python3 ~/rag-demo/convert.py
```

This will take a while — hundreds of pages, each going through
Docling's real document-structure parsing, not a simple strip-tags
regex. A handful of conversion failures on oddly-formatted 1990s pages
is expected and fine; check the `FAILED` lines but don't expect zero.

## Step 3: Create a Knowledge Collection in Open WebUI

Log into Open WebUI and:

*(Core install: `https://<configured-hostname>:8443/`. Caddy TLS is mandatory; see docs/security-hardening.md.)*

1. **Workspace → Knowledge → Create Knowledge** (a "Knowledge Base") — name
   it something like "Antenna Design (Cebik)"
2. **Upload the converted files** — the `.md` files from
   `~/rag-demo/converted`, using **Upload files** (or **Upload directory** for
   the whole folder; **Sync directory** re-syncs a folder that changes).
   Open WebUI will chunk and embed each one using the embedding model set
   in **Admin Panel → Settings → Documents**. Confirm it shows **Embedding Model
   Engine: Ollama** and model `nomic-embed-text` (chunk size 1000, overlap 100,
   top-k 3 are the defaults). A fresh install is seeded with that through the
   Quadlet; on an existing host the stored setting wins, so set it here once,
   before indexing anything. **Change the Embedding Model Engine dropdown to
   Ollama, not just the model name:** with the engine left on the default,
   Open WebUI treats `nomic-embed-text` as a Hugging Face model name and, on
   the next start, contacts `huggingface.co` looking for it (observed on this
   host, answered 401) instead of using Ollama. Changing the embedding model after documents are
   indexed means re-indexing everything.
3. Wait for indexing to complete — with hundreds of files, this takes
   real time. Open WebUI shows per-file processing status; let it finish
   before querying.

*(Menu wording may shift slightly across Open WebUI versions — if
"Knowledge" isn't where you expect, check Workspace's other tabs; the
underlying feature has been stable even when labels move. The names above were
checked against Open WebUI v0.12.0; see "Verification status" at the end.)*

## Step 4: Attach the Knowledge Base to a Chat

Two ways to use it once indexed:

- **Per-message reference:** type `#` in the chat box, select your
  "Antenna Design (Cebik)" collection — scopes retrieval to that one
  message
- **Always-on for a custom model:** Workspace → Models → create a model
  based on `qwen3:14b`, attach the Knowledge collection in its settings
  — every chat with that model retrieves from it automatically while its
  **File Context** capability is on (the default). Attach it to the Analyst
  model or to a separate research model, not to the Operator model that can
  tune receivers.

With **native function calling** (the setting the SIGINT models use), Open WebUI
also lists the attached knowledge to the model and gives it built-in knowledge
query tools, so the model may run its own follow-up searches in addition to the
automatic retrieval. If you keep **Built-in Tools** off for a model, only the
automatic retrieval applies.

For this first test, the `#` reference per-message is simpler and lets
you compare answers with and without RAG active.

## Try It Out — A Real Chat Session

With the collection indexed and referenced, try questions that only a
system that's actually retrieved from this specific corpus should
answer well — not generic antenna trivia `qwen3:14b` might already
know from training, but Cebik's own specific treatments:

- *"According to this material, what determines the feedpoint
  impedance of a center-fed dipole, and how does height above ground
  affect it?"*
- *"What does this collection say about the Moxon rectangle antenna
  and its bandwidth compared to a Yagi?"*
- *"Summarize the modeling approach described for link-coupled
  antenna tuners."*
- *"What design considerations are described for vertically radiating
  horizontal antennas?"*

**A good sanity check, not just a good demo:** ask the same question
once with the `#` Knowledge reference and once without it. If the
answers are meaningfully different — the RAG-backed one citing or
clearly drawing on specific Cebik terminology/structure the plain
answer doesn't — that's real confirmation retrieval is actually
happening, not just Ollama answering from general training data anyway.

## Tips & Troubleshooting

- **Indexing seems stuck:** check Open WebUI's own logs
  (`podman logs open-webui`) — large batches can take a while;
  distinguish "still working" from "actually stalled" the same way you
  would for any long-running background job — check for actual
  activity, not just elapsed time.
- **Answers ignore the knowledge base entirely:** confirm the `#`
  reference actually attached (it should show as a chip/tag in the
  message box before sending) and that indexing genuinely completed,
  not just started.
- **Conversion produced garbled text for some pages:** expected for a
  handful of 1990s-era pages with unusual markup — Docling's own
  structure-aware parsing handles most of it well, but not perfectly;
  spot-check a few converted `.md` files against the original HTML if
  an answer seems off.
- **Want this material in the standalone corpus too:** copy the
  converted `.md` files into `/data/corpus/source` and re-run
  `./scripts/install-ai-ingest.sh` — an independent, optional step, not
  required for the chat-session path above.

## Verification status

Checked on 2026-10-11 against Open WebUI **v0.12.0** on `dungeon`, by reading
the running container's frontend bundle, backend code, and stored settings:

| Item | Result |
|---|---|
| Workspace → Knowledge and Workspace → Models routes | Present |
| Labels "Create Knowledge", "Upload files", "Upload directory", "Sync directory", "Attach Knowledge" | Present (the old "Create a new collection" wording is gone) |
| Admin Settings → Documents with "Embedding Model Engine" | Present |
| `#` trigger in the chat box | Present in the chat input; the exact collection-picker wording was not seen rendered |
| Embedding model | Open WebUI's own default is the built-in `all-MiniLM-L6-v2`; this build sets `nomic-embed-text` via Ollama in the Quadlet (new installs) and the Documents setting (existing hosts). `nomic-embed-text` returned 768-dimension vectors through the private route |
| Knowledge with native function calling | Automatic retrieval still runs (File Context on), plus built-in knowledge tools |
| Engine set to the default while the model is `nomic-embed-text` | Misconfiguration, seen once on `dungeon`: Open WebUI asked `huggingface.co` for `sentence-transformers/nomic-embed-text` at startup. After setting the engine to Ollama, a restart showed no Hugging Face contact |
| `ai-ingest` venv and Docling (Step 2) | Docling is in `ai-ingest/requirements.txt`, but the venv is **not installed** on `dungeon` |

Not verified: the end-to-end flow (cloning the source, converting it, indexing
hundreds of files, and the example chat questions). No corpus has been indexed
on this host, so retrieval quality and indexing time are untested here. The
only network use in the whole procedure is the `git clone` in Step 1 (and a
first-time embedding-model download if the model were not already cached).

