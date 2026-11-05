"""In-container entry point: read a program from stdin, run it, emit one JSON envelope.

Runs as an unprivileged user on a read-only root filesystem; only /tmp (a size-limited
tmpfs) is writable. Files the program writes to /tmp/artifacts are returned base64-encoded.
"""

import base64
import json
import subprocess
import sys
import time
from pathlib import Path

MAX_STREAM = 256 * 1024
MAX_ARTIFACT = 512 * 1024
MAX_ARTIFACTS = 16
# Inside the sandbox /tmp is the only writable path.
TMP = Path("/tmp")  # noqa: S108
ART_DIR = TMP / "artifacts"
PROGRAM = TMP / "main.py"


def main() -> None:
    timeout = float(sys.argv[1]) if len(sys.argv) > 1 else 10.0
    code = sys.stdin.read()
    ART_DIR.mkdir(parents=True, exist_ok=True)
    PROGRAM.write_text(code)
    start = time.monotonic()
    timed_out = False
    try:
        proc = subprocess.run(  # noqa: S603 - running untrusted code is the point; it is contained
            [sys.executable, "-I", str(PROGRAM)],
            capture_output=True,
            timeout=timeout,
            cwd=TMP,
        )
        stdout, stderr, exit_code = proc.stdout, proc.stderr, proc.returncode
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        stdout, stderr, exit_code = exc.stdout or b"", exc.stderr or b"", -9
    duration = time.monotonic() - start

    artifacts = []
    for path in sorted(ART_DIR.iterdir())[:MAX_ARTIFACTS]:
        if path.is_file() and path.stat().st_size <= MAX_ARTIFACT:
            data = path.read_bytes()
            artifacts.append(
                {
                    "name": path.name,
                    "size": len(data),
                    "content_b64": base64.b64encode(data).decode(),
                }
            )

    envelope = {
        "stdout": stdout[:MAX_STREAM].decode("utf-8", "replace"),
        "stderr": stderr[:MAX_STREAM].decode("utf-8", "replace"),
        "exit_code": exit_code,
        "timed_out": timed_out,
        "duration_s": round(duration, 3),
        "truncated": len(stdout) > MAX_STREAM or len(stderr) > MAX_STREAM,
        "artifacts": artifacts,
    }
    sys.__stdout__.write(json.dumps(envelope))


if __name__ == "__main__":
    main()
