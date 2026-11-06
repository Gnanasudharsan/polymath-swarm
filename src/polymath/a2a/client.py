"""Delegate a task to an external A2A agent (any A2A-speaking system, including another swarm).

Whatever the remote agent says is treated as **untrusted input**: its answer becomes a proposed
claim with no evidence, so the verification gate can never accept it on the remote's say-so.
"""

from __future__ import annotations

import httpx
from a2a import helpers
from a2a.client import ClientConfig, ClientFactory
from a2a.types import Role, SendMessageRequest

from polymath.agents.base import AgentContext, AgentResult
from polymath.core.logging import get_logger
from polymath.core.models import AgentRole, Claim, Task
from polymath.security.untrusted import sanitize_untrusted

log = get_logger(__name__)
MAX_REMOTE_CHARS = 20_000


class A2ADelegate:
    """``TaskExecutor`` that forwards the task to a remote A2A agent."""

    def __init__(
        self,
        url: str,
        role: AgentRole,
        *,
        api_key: str | None = None,
        http: httpx.AsyncClient | None = None,
        timeout_s: float = 600.0,
    ) -> None:
        self.url, self.task_role, self.api_key = url.rstrip("/"), role, api_key
        self._http = http
        self.timeout_s = timeout_s

    def _message(self, task: Task, context: AgentContext) -> str:
        parts = [f"Problem: {context.problem.statement}", f"Task: {task.description}"]
        if context.notes:
            parts.append(f"Context from earlier tasks:\n{context.notes[:6000]}")
        return "\n\n".join(parts)

    async def run(self, task: Task, context: AgentContext) -> AgentResult:
        headers = {"x-api-key": self.api_key} if self.api_key else {}
        own = self._http is None
        http = self._http or httpx.AsyncClient(timeout=self.timeout_s)
        try:
            http.headers.update(headers)
            client = await ClientFactory(ClientConfig(httpx_client=http, streaming=False)
                                         ).create_from_url(self.url)  # fmt: skip
            message = helpers.new_text_message(self._message(task, context), role=Role.ROLE_USER)
            request = SendMessageRequest(message=message)
            texts: list[str] = []
            async for resp in client.send_message(request):
                text = helpers.get_stream_response_text(resp)
                if text:
                    texts.append(text)
        finally:
            if own:
                await http.aclose()
        raw = "\n\n".join(texts).strip() or "(empty reply)"
        answer = sanitize_untrusted(raw, max_chars=MAX_REMOTE_CHARS).text
        log.info("a2a.delegated", url=self.url, role=self.task_role.value, chars=len(answer))
        claim = Claim(
            statement=f"[external A2A agent at {self.url}] {answer[:500]}",
            confidence=0.3,
            proposed_by=self.task_role,
            task_id=task.id,
        )
        return AgentResult(task_id=task.id, role=self.task_role, output=answer, claims=[claim])
