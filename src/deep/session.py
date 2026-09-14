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
        self._routing_lock = threading.Lock()
        self._pending: dict[str, tuple[str, Queue[dict[str, Any]]]] = {}
        self._notifications: dict[str, str] = {}
        self._stream_error: dict[str, Any] | None = None
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
                    self._route_response(event)
                else:
                    self._on_event(event)
        except (ValueError, OSError) as error:
            self._fail_pending(str(error))
        finally:
            self._fail_pending("Deep process closed its output stream")

    def _route_response(self, event: dict[str, Any]) -> None:
        identifier = str(event.get("id", ""))
        with self._routing_lock:
            pending = self._pending.get(identifier)
            if pending is None and event.get("id") is None:
                pending = next((entry for entry in self._pending.values() if entry[0] in {"research", "convert", "resume"}), None)
            method = self._notifications.pop(identifier, None)
        if pending is not None:
            pending[1].put(event)
        elif method is not None:
            self._on_event({**event, "type": "control", "method": method})

    def _fail_pending(self, message: str) -> None:
        with self._routing_lock:
            if self._stream_error is None:
                self._stream_error = {"type": "error", "error": {"message": message}}
            for _method, responses in self._pending.values():
                responses.put(self._stream_error)

    def _read_errors(self) -> None:
        assert self._process.stderr is not None
        # Provider stderr may contain tokens or source excerpts. Never forward it to job logs.
        for _line in self._process.stderr:
            pass

    def notify(self, method: str, params: dict[str, Any] | None = None) -> str:
        return self._send(method, params, None)

    def _send(self, method: str, params: dict[str, Any] | None, responses: Queue[dict[str, Any]] | None) -> str:
        identifier = str(uuid.uuid4())
        request = {"protocolVersion": 1, "id": identifier, "method": method, "params": params or {}}
        with self._write_lock:
            if self._process.stdin is None or self._process.poll() is not None:
                raise RuntimeError("Deep process is not running")
            with self._routing_lock:
                if self._stream_error is not None:
                    raise RuntimeError(str(self._stream_error["error"]["message"]))
                if responses is None:
                    self._notifications[identifier] = method
                else:
                    self._pending[identifier] = (method, responses)
            try:
                self._process.stdin.write(json.dumps(request) + "\n")
                self._process.stdin.flush()
            except (OSError, ValueError):
                with self._routing_lock:
                    self._pending.pop(identifier, None)
                    self._notifications.pop(identifier, None)
                raise
        return identifier

    def request(self, method: str, params: dict[str, Any] | None = None, timeout: float | None = None) -> dict[str, Any]:
        responses: Queue[dict[str, Any]] = Queue()
        identifier = self._send(method, params, responses)
        try:
            return self._wait_response(method, responses, timeout)
        finally:
            with self._routing_lock:
                self._pending.pop(identifier, None)

    def _wait_response(self, method: str, responses: Queue[dict[str, Any]], timeout: float | None) -> dict[str, Any]:
        deadline = time.monotonic() + timeout if timeout else None
        while True:
            remaining = deadline - time.monotonic() if deadline else None
            if remaining is not None and remaining <= 0:
                raise TimeoutError(f"Deep {method} timed out")
            try:
                response = responses.get(timeout=remaining)
            except Empty as error:
                raise TimeoutError(f"Deep {method} timed out") from error
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
