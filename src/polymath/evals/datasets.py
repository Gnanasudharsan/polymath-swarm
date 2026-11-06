"""Eval suites. Public benchmarks are fetched at eval time and cached locally (not redistributed);
the custom research-QA set is committed.

- ``minif2f``: Lean 4 statements from yangky11/miniF2F-lean4 (MIT), ``mathd_*`` test problems.
- ``math``: Hendrycks MATH (MIT) via the Hugging Face datasets-server, Level 5, numeric answers.
- ``research_qa``: original questions with answer keywords (evals/datasets/research_qa).
"""

from __future__ import annotations

import json
import random
import re
from pathlib import Path
from typing import Any, Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field

Suite = Literal["minif2f", "math", "research_qa"]
ROOT = Path(__file__).resolve().parents[3] / "evals" / "datasets"
CACHE = ROOT / "cache"
MINIF2F_REPO = "yangky11/miniF2F-lean4"
MINIF2F_REV = "main"
MATH_DATASET = "EleutherAI/hendrycks_math"
MATH_CONFIGS = ("algebra", "number_theory", "counting_and_probability", "prealgebra")


class EvalProblem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    suite: Suite
    prompt: str = Field(description="What the system is asked")
    gold: str = Field(description="Boxed answer | Lean statement | ';'-separated keywords")
    meta: dict[str, Any] = Field(default_factory=dict)


def _cached_json(name: str, fetch: Any) -> Any:
    path = CACHE / name
    if path.exists():
        return json.loads(path.read_text())
    data = fetch()
    CACHE.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))
    return data


# ---------------------------------------------------------------- miniF2F

_THEOREM = re.compile(r"(theorem\s+(\w+).*?):=\s*by\s*sorry", re.DOTALL)


def _fetch_minif2f() -> list[dict[str, str]]:
    base = f"https://raw.githubusercontent.com/{MINIF2F_REPO}/{MINIF2F_REV}/MiniF2F/Test"
    listing = httpx.get(
        f"https://api.github.com/repos/{MINIF2F_REPO}/contents/MiniF2F/Test", timeout=30
    ).json()
    out = []
    for entry in listing:
        name = entry["name"]
        if name.startswith("mathd_") and name.endswith(".lean"):
            text = httpx.get(f"{base}/{name}", timeout=30).text
            m = _THEOREM.search(text)
            header = "\n".join(
                ln for ln in text.splitlines() if ln.startswith(("open ", "set_option"))
            )
            if m:
                out.append({"name": m.group(2), "statement": m.group(1).strip(), "header": header})
    return out


def minif2f_problems(n: int, seed: int = 0) -> list[EvalProblem]:
    rows = _cached_json("minif2f_mathd.json", _fetch_minif2f)
    rng = random.Random(seed)  # noqa: S311 - sampling
    picked = rng.sample(rows, min(n, len(rows)))
    return [
        EvalProblem(
            id=r["name"],
            suite="minif2f",
            prompt=(
                "Prove the following Lean 4 + Mathlib theorem. Keep the statement exactly as "
                f"given (same name, hypotheses and conclusion).\n\n```lean\n{r['header']}\n\n"
                f"{r['statement']} := by\n  sorry\n```"
            ),
            gold=r["statement"],
            meta={"header": r["header"], "name": r["name"]},
        )
        for r in picked
    ]


# ---------------------------------------------------------------- MATH


def last_boxed(text: str) -> str | None:
    """Content of the last ``\\boxed{...}`` (brace-balanced)."""
    i = text.rfind("\\boxed")
    if i < 0:
        return None
    j = text.find("{", i)
    if j < 0:
        return None
    depth = 0
    for k in range(j, len(text)):
        if text[k] == "{":
            depth += 1
        elif text[k] == "}":
            depth -= 1
            if depth == 0:
                return text[j + 1 : k].strip()
    return None


def _fetch_math() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for config in MATH_CONFIGS:
        url = "https://datasets-server.huggingface.co/rows"
        for offset in (0, 100, 200):
            data = httpx.get(url, params={"dataset": MATH_DATASET, "config": config,
                                          "split": "test", "offset": offset, "length": 100},
                             timeout=60).json()  # fmt: skip
            for item in data.get("rows", []):
                r = item["row"]
                if r["level"] == "Level 5":
                    rows.append({"id": f"{config}_{item['row_idx']}", "problem": r["problem"],
                                 "solution": r["solution"], "type": r["type"]})  # fmt: skip
    return rows


_NUMERIC = re.compile(r"^-?\d+(?:\.\d+)?$|^-?\\frac\{\d+\}\{\d+\}$|^-?\d+/\d+$")


def math_problems(n: int, seed: int = 0) -> list[EvalProblem]:
    rows = _cached_json("math_level5.json", _fetch_math)
    usable = []
    for r in rows:
        ans = last_boxed(r["solution"])
        if ans and _NUMERIC.match(ans.replace(" ", "")) and len(r["problem"]) < 700:
            usable.append((r, ans))
    rng = random.Random(seed)  # noqa: S311 - sampling
    picked = rng.sample(usable, min(n, len(usable)))
    return [
        EvalProblem(
            id=r["id"],
            suite="math",
            prompt=f"{r['problem']}\n\nGive the final answer in the form \\boxed{{...}}.",
            gold=ans,
            meta={"type": r["type"]},
        )
        for r, ans in picked
    ]


# ---------------------------------------------------------------- research QA


def research_qa_problems(n: int, seed: int = 0) -> list[EvalProblem]:
    rows = [
        json.loads(line)
        for line in (ROOT / "research_qa" / "questions.jsonl").read_text().splitlines()
        if line.strip()
    ]
    rng = random.Random(seed)  # noqa: S311 - sampling
    picked = rng.sample(rows, min(n, len(rows)))
    return [
        EvalProblem(id=r["id"], suite="research_qa", prompt=r["question"],
                    gold=";".join(r["keywords"]), meta={"source": r.get("source", "")})
        for r in picked
    ]  # fmt: skip


def load_suite(suite: Suite, n: int, seed: int = 0) -> list[EvalProblem]:
    return {"minif2f": minif2f_problems, "math": math_problems,
            "research_qa": research_qa_problems}[suite](n, seed)  # fmt: skip
