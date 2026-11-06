"""Literature: search → read abstracts → extract findings with verbatim, re-checkable quotes."""

from __future__ import annotations

from typing import ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field

from polymath.agents.base import AgentContext, AgentResult, BaseAgent, task_brief
from polymath.agents.tools import ToolCallError, Tools
from polymath.core.logging import get_logger
from polymath.core.models import AgentRole, Claim, Task
from polymath.llm.cost import LLMUsage
from polymath.llm.gateway import LLMGateway
from polymath.mcp_servers.literature.models import Paper
from polymath.mcp_servers.literature.sources import arxiv_base_id
from polymath.security.untrusted import wrap_untrusted
from polymath.verification.evidence import CitationPayload, make_evidence, quote_in_source

log = get_logger(__name__)
MAX_PAPERS = 12
FULL_TEXT_PAPERS = 2  # arXiv hits ingested (PDF → chunks) per task
MAX_PASSAGES = 6


class Query(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: Literal["arxiv", "openalex", "semantic_scholar"]
    query: str = Field(min_length=2, max_length=200)


class QueryPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    queries: list[Query] = Field(min_length=1, max_length=3)


class Finding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    statement: str = Field(min_length=1)
    paper: int = Field(ge=1, description="n of the <paper n=...> supporting it")
    quote: str = Field(min_length=1, description="verbatim from that paper's title/abstract")
    confidence: float = Field(ge=0, le=1)


class Findings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str
    findings: list[Finding] = Field(default_factory=list, max_length=8)


def citation_target(paper: Paper) -> tuple[Literal["arxiv", "openalex"], str] | None:
    """Where the gate can re-fetch this paper by id."""
    if paper.arxiv_id:
        return "arxiv", paper.arxiv_id
    if paper.source == "openalex" and paper.source_id:
        return "openalex", paper.source_id
    if paper.doi:
        return "openalex", paper.doi
    return None


class LiteratureAgent(BaseAgent):
    role: ClassVar[AgentRole] = AgentRole.LITERATURE
    prompt_name: ClassVar[str] = "literature"

    def __init__(self, gateway: LLMGateway, tools: Tools) -> None:
        super().__init__(gateway)
        self.toolset = tools

    async def run(self, task: Task, context: AgentContext) -> AgentResult:
        usage: list[LLMUsage] = []
        brief = task_brief(task, context)
        plan = await self.ask(QueryPlan, brief, usage, prompt="literature_queries")
        papers = await self._search(plan)
        passages = await self._passages(papers, " ".join(q.query for q in plan.queries))
        if not papers and not passages:
            return self.result(task, "No papers found for the planned queries.", usage)

        # Retrieved text is untrusted: sanitised, wrapped, flagged if it reads like instructions.
        items = [
            *(wrap_untrusted("paper", f"n={i}",
                             f"Title: {p.title}\nYear: {p.year}\nAbstract: {p.abstract}")
              for i, p in enumerate(papers, 1)),
            *(wrap_untrusted("paper", f"n={len(papers) + j}",
                             f"Title: {title}\nFull-text passage: {text}")
              for j, (_, title, text) in enumerate(passages, 1)),
        ]  # fmt: skip
        listing = "\n".join(items)
        found = await self.ask(Findings, f"{brief}\n\n## Search results\n{listing}", usage)

        claims: list[Claim] = []
        for f in found.findings:
            if f.paper > len(papers) + len(passages):
                continue
            if f.paper > len(papers):
                passage_claim = self._passage_claim(f, passages[f.paper - len(papers) - 1], task)
                if passage_claim is not None:
                    claims.append(passage_claim)
                continue
            paper = papers[f.paper - 1]
            target = citation_target(paper)
            claim = Claim(
                statement=f.statement,
                confidence=f.confidence,
                proposed_by=self.role,
                task_id=task.id,
            )
            # Only attach evidence the gate can reproduce: re-fetchable source + verbatim quote.
            if target and quote_in_source(f.quote, f"{paper.title}\n{paper.abstract}"):
                payload = CitationPayload(
                    source=target[0], paper_id=target[1], title=paper.title, url=paper.url,
                    quote=f.quote,
                )  # fmt: skip
                claim = claim.with_evidence(
                    make_evidence(
                        payload, summary=f"{paper.title} ({paper.year})", source=self.role
                    )
                )
            else:
                log.info("literature.unverifiable_quote", paper=paper.title)
            claims.append(claim)
        cited = "\n".join(f"- {p.title} ({p.year}) {p.url or ''}" for p in papers[:5])
        return self.result(task, f"{found.summary}\n\nTop sources:\n{cited}", usage, claims=claims)

    async def _passages(self, papers: list[Paper], query: str) -> list[tuple[str, str, str]]:
        """Ingest the top arXiv hits' full text, then retrieve passages: (key, title, text)."""
        if not self.toolset.has_knowledge:
            return []
        for p in [p for p in papers if p.arxiv_id][:FULL_TEXT_PAPERS]:
            try:
                await self.toolset.ingest_arxiv(p.arxiv_id or "")
            except ToolCallError as exc:
                log.warning("literature.ingest_failed", paper=p.arxiv_id, error=str(exc))
        try:
            hits = (await self.toolset.search_knowledge(query, k=MAX_PASSAGES)).hits
        except ToolCallError:
            return []
        titles: dict[str, str] = {}
        out = []
        for h in hits:
            key = h.chunk.paper_key
            if not key.startswith("arxiv:"):
                continue
            if key not in titles:
                stored = (await self.toolset.paper_text(key)).paper
                titles[key] = stored.title if stored else key
            out.append((key, titles[key], h.chunk.text))
        return out

    def _passage_claim(self, f: Finding, passage: tuple[str, str, str], task: Task) -> Claim | None:
        key, title, text = passage
        claim = Claim(statement=f.statement, confidence=f.confidence, proposed_by=self.role,
                      task_id=task.id)  # fmt: skip
        if not quote_in_source(f.quote, text):
            return claim
        payload = CitationPayload(
            source="arxiv", paper_id=key.removeprefix("arxiv:"), title=title,
            url=f"https://arxiv.org/abs/{arxiv_base_id(key.removeprefix('arxiv:'))}",
            quote=f.quote, location="full_text",
        )  # fmt: skip
        evidence = make_evidence(payload, summary=f"{title} (full text)", source=self.role)
        return claim.with_evidence(evidence)

    async def _search(self, plan: QueryPlan) -> list[Paper]:
        seen: set[str] = set()
        papers: list[Paper] = []
        for q in plan.queries:
            try:
                hits = await self.toolset.search_papers(q.source, q.query, limit=5)
            except ToolCallError as exc:
                log.warning("literature.search_failed", source=q.source, error=str(exc))
                continue
            for p in hits.papers:
                key = (p.doi or p.arxiv_id or p.title).lower()
                if key not in seen and p.abstract:
                    seen.add(key)
                    papers.append(p)
        return papers[:MAX_PAPERS]
