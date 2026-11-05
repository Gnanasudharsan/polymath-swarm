"""A fake toolset for agent tests. ``run_python`` really executes the (test-authored) program
in a local subprocess, so counterexample searches and checks are genuine computations."""

from __future__ import annotations

import asyncio
import json
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from polymath.agents.tools import ToolCallError
from polymath.core.config import Settings
from polymath.llm.gateway import LLMGateway
from polymath.mcp_servers.knowledge.server import PaperText, SearchResult
from polymath.mcp_servers.lean.checker import Diagnostic, LeanCheckResult, LeanVerification
from polymath.mcp_servers.literature.models import Paper, PaperList
from polymath.mcp_servers.sandbox.docker import SandboxResult
from polymath.memory.models import ChunkRecord, PaperRecord, ScoredChunk
from tests.conftest import FakeCompletion, no_sleep


def lean_result(verified: bool, reason: str = "", info: str | None = None) -> LeanVerification:
    diags = [Diagnostic(severity="info", line=1, column=0, message=info)] if info else []
    check = LeanCheckResult(ok=verified, complete=verified, diagnostics=diags, sorry_count=0)
    return LeanVerification(
        theorem="t",
        verified=verified,
        reason=reason or ("ok" if verified else "Lean reported 1 error(s)"),
        axioms=["propext"] if verified else [],
        check=check,
    )


@dataclass
class FakeTools:
    papers: dict[str, Paper] = field(default_factory=dict)  # "source:id" -> paper
    search_hits: list[Paper] = field(default_factory=list)
    lean_results: list[LeanVerification] = field(default_factory=list)
    programs: list[str] = field(default_factory=list)
    lean_calls: list[tuple[str, str]] = field(default_factory=list)
    lean_fn: Callable[[str], LeanVerification] | None = None  # decide by code instead of a script
    full_texts: dict[str, str] = field(default_factory=dict)  # "arxiv:<base id>" -> text
    ingested: list[str] = field(default_factory=list)
    stored: set[str] = field(default_factory=set)

    async def run_python(self, code: str, timeout_s: float = 30.0) -> SandboxResult:
        self.programs.append(code)
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-I", "-c", code,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )  # fmt: skip
        out, err = await asyncio.wait_for(proc.communicate(), timeout_s)
        return SandboxResult(
            stdout=out.decode(), stderr=err.decode(), exit_code=proc.returncode or 0,
            timed_out=False, duration_s=0.0,
        )  # fmt: skip

    async def sympy(self, op: str, **kwargs: Any) -> dict[str, Any]:
        raise ToolCallError("not scripted")

    async def search_papers(self, source: str, query: str, limit: int = 5) -> PaperList:
        return PaperList(query=query, source="arxiv", papers=self.search_hits[:limit])

    async def fetch_paper(self, source: str, identifier: str) -> Paper:
        key = f"{source}:{identifier}"
        if key not in self.papers:
            raise ToolCallError(f"{key} not found")
        return self.papers[key]

    async def lean_check(self, code: str) -> LeanCheckResult:
        return self.lean_results[0].check

    async def lean_verify(self, code: str, theorem_name: str) -> LeanVerification:
        self.lean_calls.append((code, theorem_name))
        if self.lean_fn is not None:
            return self.lean_fn(code)
        if not self.lean_results:
            raise ToolCallError("no scripted Lean result")
        return self.lean_results.pop(0) if len(self.lean_results) > 1 else self.lean_results[0]

    @property
    def has_knowledge(self) -> bool:
        return bool(self.full_texts)

    async def search_knowledge(self, query: str, k: int = 8) -> SearchResult:
        hits = [
            ScoredChunk(chunk=ChunkRecord(id=f"{key}#1", paper_key=key, ord=1, page=3, text=text),
                        score=1.0, sources=["fake"])
            for key, text in self.full_texts.items() if key in self.stored
        ]  # fmt: skip
        return SearchResult(query=query, hits=hits[:k])

    async def ingest_arxiv(self, arxiv_id: str) -> PaperRecord:
        key = f"arxiv:{arxiv_id.split('v')[0]}"
        self.ingested.append(arxiv_id)
        self.stored.add(key)
        return PaperRecord(key=key, title=key)

    async def paper_text(self, paper_key: str) -> PaperText:
        text = self.full_texts.get(paper_key, "") if paper_key in self.stored else ""
        return PaperText(paper=None, text=text)


def gateway(settings: Settings, replies: list[Any]) -> tuple[LLMGateway, FakeCompletion]:
    fake = FakeCompletion([r if isinstance(r, str) else json.dumps(r) for r in replies])
    return LLMGateway(settings, completion_fn=fake, sleep=no_sleep), fake


EULER_COUNTEREXAMPLE = """
from sympy import isprime
for n in range(0, 100):
    v = n * n + n + 41
    if not isprime(v):
        factor = next(p for p in range(2, v) if v % p == 0)
        print(f"POLYMATH_COUNTEREXAMPLE: n={n} gives {v}, divisible by {factor}")
        break
"""
