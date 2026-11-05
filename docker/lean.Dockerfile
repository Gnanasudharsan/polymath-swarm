# Lean 4 + Mathlib checker image for the `lean` MCP server.
# Build:  docker build -f docker/lean.Dockerfile -t polymath-lean:v4.35.0 docker/lean
# The image holds a Lake project with Mathlib's prebuilt .olean cache plus the
# leanprover-community REPL, which the server keeps running so Mathlib is loaded once.
FROM ubuntu:24.04

ARG ELAN_VERSION=v4.2.4
ARG LEAN_TOOLCHAIN=leanprover/lean4:v4.35.0
ARG MATHLIB_REV=v4.35.0
ARG REPL_REV=v4.35.0

RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates curl git \
 && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --uid 10001 lean
USER lean
WORKDIR /home/lean
ENV PATH="/home/lean/.elan/bin:${PATH}"

RUN curl -sSfL "https://raw.githubusercontent.com/leanprover/elan/${ELAN_VERSION}/elan-init.sh" -o elan-init.sh \
 && sh elan-init.sh -y --no-modify-path --default-toolchain "${LEAN_TOOLCHAIN}" \
 && rm elan-init.sh

WORKDIR /home/lean/project
COPY --chown=lean:lean lakefile.toml ./
RUN echo "${LEAN_TOOLCHAIN}" > lean-toolchain \
 && sed -i "s/@MATHLIB_REV@/${MATHLIB_REV}/" lakefile.toml \
 && lake update \
 && lake exe cache get \
 && printf 'import Mathlib\n#eval 1 + 1\n' > Smoke.lean \
 && lake env lean Smoke.lean \
 && rm Smoke.lean

# REPL (JSON over stdin/stdout); built against the same toolchain as Mathlib.
WORKDIR /home/lean
RUN git clone --depth 1 --branch "${REPL_REV}" https://github.com/leanprover-community/repl.git \
 && cd repl && lake build && rm -rf .git

WORKDIR /home/lean/project
# Default: REPL with Mathlib on the search path. `lake env lean --json --stdin` also works.
ENTRYPOINT ["lake", "env", "/home/lean/repl/.lake/build/bin/repl"]
