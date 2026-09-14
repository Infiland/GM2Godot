"""Streaming versioned subprocess protocol with durable request provenance."""
from __future__ import annotations

import json
import os
import signal
import subprocess
import threading
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from queue import Empty, Queue
from typing import Any, cast


def _ignore_event(_event: dict[str, Any]) -> None:
    pass


class DeepSession:
    def __init__(self, command: list[str], job_root: Path, on_event: Callable[[dict[str, Any]], None] | None = None, environment: dict[str, str] | None = None) -> None:
        self.job_root = job_root
        self.job_root.mkdir(parents=True, exist_ok=True)
        self._on_event: Callable[[dict[str, Any]], None] = on_event or _ignore_event
        self._write_lock = threading.Lock()
        self._close_lock = threading.Lock()
        self._responses: Queue[dict[str, Any]] = Queue()
        self._process = subprocess.Popen(
            command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", bufsize=1, env={**os.environ, **(environment or {})},
            start_new_session=os.name != "nt",
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
        )
        threading.Thread(target=self._read, daemon=True).start()
        threading.Thread(target=self._read_errors, daemon=True).start()

    def _read(self) -> None:
        assert self._process.stdout is not None
        try:
            for line in self._process.stdout:
                event: dict[str, Any] = json.loads(line)
                if event.get("protocolVersion") != 1:
                    raise ValueError("Unsupported Deep response protocol")
                if event.get("type") in {"result", "error", "completed"}:
                    self._responses.put(event)
                else:
                    self._on_event(event)
        except (ValueError, OSError) as error:
            self._responses.put({"type": "error", "error": {"message": str(error)}})
        finally:
            self._responses.put({"type": "error", "error": {"message": "Deep process closed its output stream"}})

    def _read_errors(self) -> None:
        assert self._process.stderr is not None
        # Provider stderr may contain tokens or source excerpts. Never forward it to job logs.
        for _line in self._process.stderr:
            pass

    def notify(self, method: str, params: dict[str, Any] | None = None) -> str:
        identifier = str(uuid.uuid4())
        request = {"protocolVersion": 1, "id": identifier, "method": method, "params": params or {}}
        with self._write_lock:
            if self._process.stdin is None or self._process.poll() is not None:
                raise RuntimeError("Deep process is not running")
            self._process.stdin.write(json.dumps(request) + "\n")
            self._process.stdin.flush()
        return identifier

    def request(self, method: str, params: dict[str, Any] | None = None, timeout: float | None = None) -> dict[str, Any]:
        identifier = self.notify(method, params)
        deadline = time.monotonic() + timeout if timeout else None
        while True:
            remaining = deadline - time.monotonic() if deadline else None
            if remaining is not None and remaining <= 0:
                raise TimeoutError(f"Deep {method} timed out")
            try:
                response = self._responses.get(timeout=remaining)
            except Empty as error:
                raise TimeoutError(f"Deep {method} timed out") from error
            if response.get("id") not in {identifier, None}:
                continue
            if response.get("type") == "error" or response.get("error"):
                failure = response.get("error", {})
                raise RuntimeError(str(failure.get("message", "Deep request failed")))
            result = response.get("result", {})
            if not isinstance(result, dict):
                raise ValueError("Deep result must be an object")
            terminal = cast(dict[str, Any], result).get("state") in {"review", "complete", "partial", "paused", "cancelled"}
            if method in {"research", "convert", "resume"} and response.get("type") != "completed" and not terminal:
                continue
            return response

    def close(self) -> None:
        with self._close_lock:
            self._close_process()

    def _close_process(self) -> None:
        process = self._process
        if process.poll() is None:
            if process.stdin is not None:
                process.stdin.close()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                if os.name == "nt":
                    subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True, check=False)
                else:
                    try:
                        os.killpg(process.pid, signal.SIGTERM)
                        process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                process.wait(timeout=5)
        for stream in (process.stdin, process.stdout, process.stderr):
            if stream is not None:
                stream.close()
