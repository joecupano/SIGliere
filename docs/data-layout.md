# AI-tier data layout

SIGliere stores only AI and optional reference data:

```text
/data/models                     Ollama model weights
/data/corpus/source              optional AI ingest inputs
/data/corpus/processed           optional normalized text
/data/reference/sigid            optional SigID mirror
/data/reference/mac-vendors      optional MAC vendor mirror
/data/imagery                    optional analysis inputs
/data/audio                      optional transcription inputs
```

Collection databases, packet captures, IQ, SigMF, and receiver recordings
belong to SIGedge and are not part of this layout. Open WebUI's core state,
uploads, and vector store live in the `open-webui-state` Podman volume.

