// Server-side proxy to the Polymath API: keeps the API key out of the browser and streams SSE.
import type { NextRequest } from "next/server";

const API = process.env.POLYMATH_API_URL ?? "http://localhost:8000";
const KEY = process.env.POLYMATH_API_KEY ?? "";

async function forward(req: NextRequest, ctx: RouteContext<"/api/polymath/[...path]">) {
  const { path } = await ctx.params;
  const url = new URL(`${API}/${path.map(encodeURIComponent).join("/")}`);
  url.search = req.nextUrl.search;
  const upstream = await fetch(url, {
    method: req.method,
    headers: {
      "x-api-key": KEY,
      "content-type": req.headers.get("content-type") ?? "application/json",
      accept: req.headers.get("accept") ?? "*/*",
    },
    body: req.method === "GET" ? undefined : await req.text(),
    cache: "no-store",
    signal: req.signal,
  });
  const headers = new Headers({
    "content-type": upstream.headers.get("content-type") ?? "application/json",
    "cache-control": "no-cache, no-transform",
  });
  return new Response(upstream.body, { status: upstream.status, headers });
}

export const GET = forward;
export const POST = forward;
