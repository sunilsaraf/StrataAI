# StrataAI

**"Strata" -> storage layers** -- Lustre connection + tiering intelligence with AI.

StrataAI is a **Cognitive Agentic Storage Control Plane** for HPC environments.
It combines a Lustre filesystem connector, an AI-driven tiering engine, an MCP
Agent Orchestrator with RAG retrieval, a Cassandra metadata backend, an IAM
policy layer, and an AI Gateway into one cohesive system.

---

## Architecture

```
+----------------------------------------------------------+
|                        User                              |
+---------------------------+------------------------------+
                            |
+---------------------------v------------------------------+
|                      AI Gateway                          |
+---------------------------+------------------------------+
                            |
+---------------------------v------------------------------+
|              Agent Orchestrator (MCP)                    |
+------------------+-------------------+------------------+
                   |                   |
     +-------------v------+   +--------v--------------+
     |   Tool Calls (MCP) |   |   RAG Retrieval        |
     |  getObjectMetadata |   |  (Vector DB)           |
     |  getBucketStats    |   |                        |
     |  getUserPolicy     |   |  - usage patterns      |
     +------+------+------+   |  - object classif.     |
            |      |          |  - policy knowledge    |
     +------v+  +--v------+   +--------+--------------+
     |Cassandra|  | IAM    |            |
     | Backend |  | Layer  |   Metadata Embeddings
     +---------+  +--------+   + Logs
                            |
             +--------------v--------------+
             |      LLM reasoning          |
             |   over tool + RAG context   |
             +------------------------------+
```

### Module overview

| Module | Description |
|--------|-------------|
| `strataai.lustre` | Lustre `lfs` CLI abstraction (`getstripe`, `migrate`, `find`) |
| `strataai.tiering` | Hot/Warm/Cold tier definitions, threshold policy, migration engine |
| `strataai.intelligence` | Time-decayed heat scoring (`PatternAnalyzer`) |
| `strataai.control_plane` | `StrataAgent` – background Observe->Analyse->Plan->Act loop |
| `strataai.storage.cassandra` | `ObjectMetadata`, `BucketStats`, `InMemoryCassandraBackend` |
| `strataai.storage.iam` | `UserPolicy`, `IamLayer`, `InMemoryIamBackend` |
| `strataai.rag.store` | `InMemoryVectorStore` – TF-normalised bag-of-words cosine similarity |
| `strataai.rag.retriever` | `RagRetriever` – usage patterns / object classification / policy knowledge |
| `strataai.mcp.tools` | `McpTools` – `getObjectMetadata()`, `getBucketStats()`, `getUserPolicy()` |
| `strataai.mcp.orchestrator` | `AgentOrchestrator` – tool calls + RAG + LLM reasoning |
| `strataai.gateway` | `AiGateway` – single entry point for user requests |

---

## Quick start

```python
from strataai import (
    AiGateway,
    AgentOrchestrator,
    GatewayRequest,
    InMemoryCassandraBackend,
    InMemoryIamBackend,
    InMemoryVectorStore,
    IamLayer,
    McpTools,
    RagRetriever,
)
from strataai.rag.retriever import CATEGORY_USAGE_PATTERN
from strataai.rag.store import Document
from strataai.storage.cassandra import ObjectMetadata, BucketStats

# --- Storage layer ---
cass = InMemoryCassandraBackend()
cass.put_object_metadata(
    ObjectMetadata(bucket="scratch", key="sim/output.h5", size_bytes=10 * 1024**3, tier="warm")
)
cass.update_bucket_stats(BucketStats(bucket="scratch", object_count=1, total_bytes=10 * 1024**3))

# --- IAM layer ---
iam = IamLayer(backend=InMemoryIamBackend())

# --- RAG retrieval ---
store = InMemoryVectorStore()
store.add(Document(
    text="simulation output accessed hourly by post-processing jobs",
    category=CATEGORY_USAGE_PATTERN,
))
retriever = RagRetriever(store=store)

# --- MCP tools + orchestrator ---
tools = McpTools(cassandra=cass, iam=iam)
orchestrator = AgentOrchestrator(tools=tools, retriever=retriever)

# --- AI Gateway ---
gateway = AiGateway(orchestrator=orchestrator)
response = gateway.process(GatewayRequest(
    user_id="alice",
    query="should sim/output.h5 be promoted to the hot tier?",
    bucket="scratch",
    object_key="sim/output.h5",
))
print(response.answer)
print(f"Tool calls: {response.tool_results_count}, RAG docs: {response.retrieved_docs_count}")
```

---

## MCP tool calls

| Tool | Arguments | Returns |
|------|-----------|---------|
| `getObjectMetadata(bucket, key)` | bucket name, object key | `ObjectMetadata` |
| `getBucketStats(bucket)` | bucket name | `BucketStats` |
| `getUserPolicy(user_id)` | user identifier | `UserPolicy` |

---

## RAG retrieval categories

| Category | Constant | Description |
|----------|----------|-------------|
| Usage patterns | `CATEGORY_USAGE_PATTERN` | Historical I/O access patterns |
| Object classification | `CATEGORY_OBJECT_CLASSIFICATION` | Size, type, and access profile docs |
| Policy knowledge | `CATEGORY_POLICY_KNOWLEDGE` | IAM rules and examples |

---

## Storage tiers (Lustre)

| Tier | Pool name | Typical backing | Default stripe count |
|------|-----------|-----------------|----------------------|
| HOT  | `hot`     | NVMe flash OSTs | 4 |
| WARM | `warm`    | HDD OSTs        | 2 |
| COLD | `cold`    | Tape / nearline | 1 |

---

## Development

```bash
pip install -e ".[dev]"
pytest
```
