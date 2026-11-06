# Polymath Swarm — web UI

Next.js 16 (App Router, Cache Components) + Tailwind + shadcn/ui + React Flow + KaTeX.

- **New problem**: problem text, run budget, optional plan approval.
- **Run view**: live task graph (React Flow; nodes light up as agents work), claims with evidence
  badges (📚 citation · 🧮 computation · ✅ Lean · ♻️ recalled from memory), cost meter, plan
  approval / replan with feedback, activity stream, and the final evidence report with KaTeX maths.

The browser never sees the API key: `src/app/api/polymath/[...path]/route.ts` proxies every call
(including the SSE event stream) to the FastAPI backend and adds `x-api-key` server-side.

## Run locally

Start the API from the repo root (see the main README), then:

```bash
npm install
```

```bash
POLYMATH_API_URL=http://localhost:8000 POLYMATH_API_KEY=<your key> npm run dev
```

Open http://localhost:3000. (If Langfuse is running on :3000, use `npm run dev -- -p 3100`.)

## End-to-end test

`npx playwright test` starts the real backend with a deterministic mock LLM (no API cost, but the
sandbox and the verification gate are real) plus the production build, solves a problem through
the UI (approve plan → live graph → verified claim → KaTeX report) and saves screenshots to
`docs/images/`. Needs Docker and the sandbox image (`docker compose --profile tools build sandbox`).

```bash
npx playwright install chromium
```

```bash
npx playwright test
```
