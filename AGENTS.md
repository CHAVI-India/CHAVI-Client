# CHAVI-Client

Graphify is available in the venv. Use that to generate the query 

## Codebase navigation: query the graphify graph BEFORE grepping

A knowledge graph of this repo lives in `graphify-out/` (built from
`client_app`, `data_import`, `dicom_archive`, `dicom_server`, `extractor`,
`templates`). Before grepping or reading files to answer a codebase question
or scope a change, query the graph:

- `graphify query "<question>"`   — broad context (BFS), returns file:line per node
- `graphify explain "<symbol>"`   — what a symbol is + everything wired to it
- `graphify path "<A>" "<B>"`     — relationship chain between two concepts
- `graphify affected "<symbol>"`  — everything that depends on it (refactor blast radius)
- `graphify god-nodes`            — core abstractions to be careful around

Use the graph to find the right files and scope the blast radius, THEN read the
actual code before editing. The graph is a map, not a substitute for reading code.

Keep it fresh: after code changes run `graphify --update` (re-extracts only
changed files; no LLM needed for code). A post-commit hook auto-rebuilds on
commit if installed (`graphify hook status`).

Treat INFERRED edges (~11% of the graph) as "likely related, verify" — not ground truth.
