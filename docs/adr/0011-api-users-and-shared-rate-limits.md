# ADR-0011: API users, run ownership and shared rate limits

- **Status:** Accepted
- **Date:** 2026-11-06

## Context

v1.0.0 had one shared API key, so every client could see, approve and resume every run, and rate
limits lived in each process's memory, so N API replicas allowed N times the intended rate. Both
were listed as known gaps.

## Decision

**Named users with hashed keys.**
- `POLYMATH_API_USERS` maps user names to `sha256:<hex>` key hashes. The server stores and compares
  only hashes (constant time, every entry checked). `polymath keys new <user>` prints a fresh key
  once, plus the hash line for the config.
- `POLYMATH_API_ADMINS` (default `["admin"]`) lists users who see every run.
- The v1.0 `POLYMATH_API_KEY` still works and means the user `admin`, so existing deployments keep
  working unchanged.
- No user database or sign-up flow: keys are configuration. That fits a self-hosted research tool
  with a handful of users and avoids storing account state.

**Run ownership.**
- The `run_started` event records `owner`. REST and A2A runs both record it (A2A carries the
  authenticated user into the executor through a `ServerCallContextBuilder`; the raw key is dropped
  from the call context).
- Non-admins list only their own runs. For another user's run, every endpoint returns the same 404
  as for a run that does not exist, so run ids cannot be probed.
- Runs created before 1.1 have no owner and are admin-only.
- The web UI proxy holds one key, so the UI acts as that one user.

**Shared rate limits.** `POLYMATH_RATE_LIMIT_BACKEND=redis` keeps the sliding window in a Redis
sorted set, updated atomically by a Lua script that uses the Redis server clock (replicas with
skewed clocks still agree). If Redis is unreachable the limiter fails open and logs a warning: a
limiter outage must not take the API down, and the per-run budget and spend cap still bound cost.
The compose `app` stack uses Redis; `polymath serve` defaults to in-memory.

## Consequences

- Multi-user and multi-replica deployments are supported without new services.
- Not covered: per-user spend quotas, key rotation tooling beyond editing the config, and roles
  finer than user/admin.
