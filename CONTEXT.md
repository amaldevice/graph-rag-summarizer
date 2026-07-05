# Graph RAG Summarizer

This context covers how operators ingest PDFs, retrieve chunks, and run summarization workflows against Qdrant-backed document collections. It defines the user-facing language for launcher behavior and runtime choices.

## Language

**Launch Profile**:
A named runtime profile that selects one coherent infrastructure pairing for a run. A launch profile describes where vectors and images live, not what work is executed.
_Avoid_: backend combo, infra mode

**Launcher Mode**:
A human-facing run type chosen at startup, such as ingesting a document, retrieving chunks, or running the full summarization flow.
_Avoid_: command, option set

**Stable Default**:
A configuration value expected to remain consistent across many runs and therefore stored in repository configuration instead of being asked every time.
_Avoid_: prompt answer, session value

**Session Override**:
A per-run choice that changes launcher behavior without rewriting stored defaults.
_Avoid_: saved preference, permanent setting

**Collection Target**:
The Qdrant collection that a run reads from or writes to.
_Avoid_: dataset, index name

**Ingest Run**:
A launcher mode that reads a source PDF and writes its chunk embeddings into a Collection Target.
_Avoid_: upload job, indexing pass

**Query-Only Run**:
A launcher mode that retrieves ranked chunks from a Collection Target without graph construction, summarization, or evaluation.
_Avoid_: basic RAG, search mode

**Full-Pipeline Run**:
A launcher mode that continues from retrieval into graph construction, summarization, evaluation, and quality decisions.
_Avoid_: normal mode, default run
