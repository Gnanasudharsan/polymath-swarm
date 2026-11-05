# Locked-down Python execution image for the `sandbox` MCP server.
# Build:  docker build -f docker/sandbox.Dockerfile -t polymath-sandbox:latest docker/sandbox
# Run-time hardening (no network, read-only FS, limits, dropped caps) is applied by the
# server's `docker run` flags; see src/polymath/mcp_servers/sandbox/docker.py.
FROM python:3.12.16-slim

RUN pip install --no-cache-dir numpy==2.5.4 scipy==1.18.1 sympy==1.14.0 mpmath==1.3.0 \
 && rm -rf /root/.cache

COPY runner.py /opt/sandbox/runner.py
RUN chmod 0555 /opt/sandbox/runner.py

USER 65534:65534
WORKDIR /tmp
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 HOME=/tmp
ENTRYPOINT ["python", "-I", "/opt/sandbox/runner.py"]
