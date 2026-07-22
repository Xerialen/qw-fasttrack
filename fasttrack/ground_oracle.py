"""Persistent subprocess client for the rex ``bsp-probe`` JSONL oracle."""
from __future__ import annotations

import hashlib
import json
import os
import queue
import subprocess
import threading
from pathlib import Path

PROTOCOL_VERSION = 1
DEFAULT_TIMEOUT_S = 5.0
DEFAULT_MAP_DIR = Path.home() / ".local" / "share" / "route-lab" / "nav-ab" / "qw" / "maps"
AUTO_PROBE = Path("/mnt/c/Users/benya/projects/quakeworld/rex/target/release/bsp-probe")
PROBE_ENV = "FASTTRACK_BSP_PROBE"
PROBE_COMMIT_ENV = "FASTTRACK_BSP_PROBE_COMMIT"


class OracleUnavailable(RuntimeError):
    """The run cannot continue as an oracle run and must restart as heuristic-only."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.reason = {"code": code, "message": message}


def resolve_map(map_parameter: str | os.PathLike[str]) -> Path:
    candidate = Path(map_parameter).expanduser()
    if candidate.suffix.lower() == ".bsp" or candidate.parent != Path("."):
        path = candidate
    else:
        path = DEFAULT_MAP_DIR / f"{candidate.name}.bsp"
    if not path.is_file():
        raise OracleUnavailable("map_not_found", f"BSP not found: {path}")
    return path.resolve()


def discover_probe(explicit: str | os.PathLike[str] | None = None) -> Path:
    configured = explicit or os.environ.get(PROBE_ENV)
    path = Path(configured).expanduser() if configured else AUTO_PROBE
    if not path.is_file():
        source = f"{PROBE_ENV}={configured}" if configured else f"auto path {AUTO_PROBE}"
        raise OracleUnavailable("probe_not_found", f"bsp-probe unavailable ({source})")
    return path.resolve()


def _probe_commit(binary: Path) -> str:
    configured = os.environ.get(PROBE_COMMIT_ENV)
    if configured:
        return configured
    try:
        commit = subprocess.run(
            [str(binary), "--probe-commit"],
            check=True, capture_output=True, text=True, timeout=2.0,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError) as error:
        raise OracleUnavailable("probe_commit_unavailable", str(error)) from error
    if len(commit) != 40 or any(char not in "0123456789abcdef" for char in commit.lower()):
        raise OracleUnavailable("probe_commit_invalid", f"bsp-probe returned {commit!r}")
    return commit


class GroundOracle:
    """One long-lived ``bsp-probe`` process, loaded with one BSP."""

    def __init__(self, map_parameter: str | os.PathLike[str],
                 probe_path: str | os.PathLike[str] | None = None,
                 timeout_s: float = DEFAULT_TIMEOUT_S):
        self.map_path = resolve_map(map_parameter)
        self.binary = discover_probe(probe_path)
        self.timeout_s = timeout_s
        self.bsp_sha = hashlib.sha256(self.map_path.read_bytes()).hexdigest()
        self.probe_commit = _probe_commit(self.binary)
        self.unknown_fallbacks: list[dict] = []
        self._responses: queue.Queue[str | None] = queue.Queue()
        try:
            self._process = subprocess.Popen(
                [str(self.binary), "--map", str(self.map_path)],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
                bufsize=1,
            )
        except OSError as error:
            raise OracleUnavailable("probe_start_failed", str(error)) from error
        assert self._process.stdout is not None
        self._reader = threading.Thread(target=self._read_stdout, daemon=True)
        self._reader.start()
        try:
            hello = self._read_json("probe_handshake")
            if hello != {"v": PROTOCOL_VERSION}:
                raise OracleUnavailable("protocol_mismatch", f"expected {{'v': 1}}, got {hello!r}")
        except Exception:
            self.close()
            raise

    def _read_stdout(self) -> None:
        assert self._process.stdout is not None
        for line in self._process.stdout:
            self._responses.put(line)
        self._responses.put(None)

    def _read_json(self, phase: str) -> dict:
        try:
            line = self._responses.get(timeout=self.timeout_s)
        except queue.Empty as error:
            raise OracleUnavailable("probe_timeout", f"{phase} exceeded {self.timeout_s:g}s") from error
        if line is None:
            code = self._process.poll()
            raise OracleUnavailable("probe_crashed", f"bsp-probe exited during {phase} (code {code})")
        try:
            value = json.loads(line)
        except json.JSONDecodeError as error:
            raise OracleUnavailable("invalid_response", f"{phase}: {error}") from error
        if not isinstance(value, dict):
            raise OracleUnavailable("invalid_response", f"{phase}: expected object")
        return value

    def probe(self, point: tuple[float, float, float] | list[float]) -> dict:
        if self._process.poll() is not None:
            raise OracleUnavailable("probe_crashed", f"bsp-probe exited with code {self._process.returncode}")
        assert self._process.stdin is not None
        try:
            self._process.stdin.write(json.dumps({"p": list(point)}, separators=(",", ":")) + "\n")
            self._process.stdin.flush()
        except (BrokenPipeError, OSError) as error:
            raise OracleUnavailable("probe_crashed", str(error)) from error
        response = self._read_json("point query")
        required = {"grounded", "floor_z", "normal_z", "contents", "status"}
        if set(response) != required or response["status"] not in {"ok", "solid", "unknown", "error"}:
            raise OracleUnavailable("invalid_response", f"invalid point response: {response!r}")
        if response["status"] == "error":
            raise OracleUnavailable("probe_error", f"bsp-probe rejected point {list(point)!r}")
        return response

    def note_unknown(self, index: int, point, response: dict) -> None:
        self.unknown_fallbacks.append({
            "sample_index": index,
            "p": [round(float(value), 3) for value in point],
            "status": response["status"],
            "fallback_method": "heuristic",
        })

    def evidence(self) -> dict:
        return {
            "method": "oracle",
            "bsp_sha": self.bsp_sha,
            "probe_commit": self.probe_commit,
            "unknown_fallbacks": list(self.unknown_fallbacks),
        }

    def close(self) -> None:
        process = getattr(self, "_process", None)
        if process is None:
            return
        if process.stdin is not None:
            try:
                process.stdin.close()
            except OSError:
                pass
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=1.0)
        if process.stdout is not None:
            process.stdout.close()
        reader = getattr(self, "_reader", None)
        if reader is not None and reader is not threading.current_thread():
            reader.join(timeout=1.0)

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.close()


def heuristic_evidence(reason: dict | None = None) -> dict:
    evidence = {"method": "heuristic", "bsp_sha": None, "probe_commit": None,
                "unknown_fallbacks": []}
    if reason is not None:
        evidence["fallback_reason"] = reason
    return evidence
