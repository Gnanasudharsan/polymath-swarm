# Architecture

Polymath Swarm is a **verification-first** multi-agent system: no claim reaches the final answer
unless it carries machine-checkable evidence.

## System overview

```mermaid
flowchart TD
    U[User problem] --> S[Supervisor / Planner]
    S -->|decomposes| G[(Task DAG<br/>Pydantic TaskGraph)]
    G --> R{Router<br/>dispatch ready tasks}
    R --> LIT[Literature Agent]
    R --> REA[Reasoner Agent]
    R --> CMP[Compute Agent]
    R --> FOR[Formalizer Agent]
    R --> CRI[Critic Agent]
    LIT & REA & CMP & FOR & CRI <--> BB[(Blackboard<br/>Redis pub/sub + Postgres)]
    BB --> CS[(Claims store)]
    CS --> VG{Verification gate}
    VG -->|verified| SYN[Synthesizer Agent]
    VG -->|unverified| CONJ[Conjectures section]
    CRI -.->|refuted → replan| S
    SYN --> OUT[Final answer + evidence report<br/>Markdown + JSON + trace]
    CONJ --> OUT
    B[Budget controller] -.->|USD / tokens / time / iterations| S

    subgraph Tools [MCP tool servers]
      T1[literature: arXiv · Semantic Scholar · OpenAlex]
      T2[sandbox: locked-down Python]
      T3[sympy]
      T4[lean: Lean 4 + Mathlib]
    end
    LIT --> T1
    CMP --> T2 & T3
    FOR --> T4
```

## Components

| Component | Module | Responsibility | Phase |
|---|---|---|---|
| Core models | `polymath.core` | `Problem`, `Task`, `TaskGraph`, `Claim`, `Evidence`, `AgentMessage`, `BlackboardEvent`, `RunBudget`; settings, logging, tracing | 1 |
| LLM gateway | `polymath.llm` | LiteLLM routing, role→model map, retries, structured output, cost accounting | 1 |
| Agents | `polymath.agents` | `BaseAgent` + six specialists; prompts versioned under `agents/prompts/` | 1, 4 |
| Tools | `polymath.mcp_servers` | FastMCP servers: literature, sandbox, sympy, lean; MCP client adapter | 2 |
| Orchestration | `polymath.graph` | LangGraph `StateGraph`, supervisor, router, Postgres checkpointer, HITL interrupts | 3 |
| Blackboard | `polymath.blackboard` | Redis pub/sub for live events, Postgres for durable history | 3 |
| Memory | `polymath.memory` | pgvector paper chunks, hybrid retrieval, episodic memory, claims store | 5 |
| Interop | `polymath.a2a` | A2A Agent Cards, server and client | 8 |
| API | `polymath.api` | FastAPI, SSE run streaming, API-key auth | 7 |
| Frontend | `frontend/` | Next.js + React Flow live task graph, claim panel, cost meter | 7 |

## Claim lifecycle

```mermaid
stateDiagram-v2
    [*] --> proposed
    proposed --> challenged: Critic objection
    challenged --> proposed: revised by Reasoner
    proposed --> verified: evidence passes gate
    challenged --> refuted: counterexample / failed check
    proposed --> refuted
    verified --> [*]
    refuted --> [*]
```

Evidence accepted by the gate:

- **citation** — the quoted source text was retrieved and actually supports the claim
- **computation** — code re-executed in the sandbox reproduces the result
- **formal_proof** — the Lean 4 file compiles against Mathlib with zero `sorry`/`admit`

## Budget & degradation

Every run carries a `RunBudget` (max USD, tokens, wall-clock, iterations). The supervisor checks
remaining budget before dispatching; near the ceiling it drops optional critics and routes to cheaper
models, and at the ceiling it terminates and synthesizes with whatever has been verified.

## Infrastructure (dev)

`docker compose up -d --wait` starts Postgres 16 + pgvector (host port 5544) and Redis 7 (6379).
Langfuse, the sandbox image, the Lean image and the API are added in later phases.
