# Retrieval eval — 2026-11-05

Corpus: 60 passages (12 topics, 5 near-neighbour passages each); 30 paraphrased queries. Embedder `BAAI/bge-small-en-v1.5`, reranker `Xenova/ms-marco-MiniLM-L-6-v2`, store Postgres 16 + pgvector (HNSW) + full-text search.

| mode | recall@1 | recall@5 | recall@10 | MRR |
|---|---|---|---|---|
| lexical | 0.817 | 0.983 | 0.983 | 0.897 |
| vector | 0.767 | 0.917 | 0.933 | 0.867 |
| hybrid | 0.833 | 0.917 | 1.000 | 0.909 |
| hybrid_rerank | 0.900 | 0.950 | 0.983 | 0.950 |

Misses (no relevant passage in the top 10): vector: ['q02', 'q07']
