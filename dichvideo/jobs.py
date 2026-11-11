"""Hàng đợi công việc: mỗi lúc chỉ xử lý một dự án (nhận dạng và mã hoá đều ngốn CPU)."""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field

from . import pipeline, projects

log = logging.getLogger(__name__)


@dataclass
class Job:
    project_id: str
    steps: list[str]
    auto: bool = False
    cancel: threading.Event = field(default_factory=threading.Event)
    created: float = field(default_factory=time.time)
    result: str = ""


class JobManager:
    def __init__(self) -> None:
        self._queue: deque[Job] = deque()
        self._current: Job | None = None
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None
        self._stop = False

    def start(self) -> None:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._stop = False
            self._thread = threading.Thread(target=self._loop, daemon=True, name="hang-doi")
            self._thread.start()

    def shutdown(self) -> None:
        self._stop = True
        with self._lock:
            for job in self._queue:
                job.cancel.set()
            if self._current:
                self._current.cancel.set()
        self._wake.set()

    def busy(self, pid: str) -> bool:
        with self._lock:
            return (self._current is not None and self._current.project_id == pid) or any(
                j.project_id == pid for j in self._queue)

    def submit(self, pid: str, steps: list[str] | None = None) -> Job:
        data = projects.load(pid)
        if not data["source"].get("ready"):
            raise projects.ProjectError("Video nguồn chưa sẵn sàng (đang tải lên hoặc tải về).", 409)
        if self.busy(pid):
            raise projects.ProjectError("Dự án này đang được xử lý hoặc đang chờ trong hàng đợi.", 409)
        auto = not steps
        plan = pipeline.plan_steps(data, steps)
        if not plan:
            raise projects.ProjectError("Không còn bước nào cần chạy.", 400)
        job = Job(pid, plan, auto=auto)

        def mark(d: dict) -> None:
            for s in plan:
                st = d["steps"][s]
                st["prev_status"] = st.get("status", "pending")
                st.update(status="queued", progress=0.0, message="Đang chờ đến lượt…", error="")

        projects.update(pid, mark)
        pipeline.clear_outputs(pid, plan)
        with self._lock:
            self._queue.append(job)
        self.start()
        self._wake.set()
        return job

    def cancel(self, pid: str) -> bool:
        with self._lock:
            found = False
            if self._current and self._current.project_id == pid:
                self._current.cancel.set()
                found = True
            for job in list(self._queue):
                if job.project_id == pid:
                    job.cancel.set()
                    self._queue.remove(job)
                    pipeline._reset_queued(pid, job.steps)
                    found = True
            return found

    def state(self) -> dict:
        with self._lock:
            return {
                "current": {"project_id": self._current.project_id, "steps": self._current.steps}
                if self._current else None,
                "queued": [{"project_id": j.project_id, "steps": j.steps} for j in self._queue],
            }

    def _loop(self) -> None:
        while not self._stop:
            with self._lock:
                job = self._queue.popleft() if self._queue else None
                self._current = job
            if job is None:
                self._wake.wait(1.0)
                self._wake.clear()
                continue
            try:
                job.result = pipeline.run_steps(job.project_id, job.steps, job.cancel, auto=job.auto)
            except projects.ProjectError as e:  # dự án bị xoá trong lúc chờ
                log.warning("Bỏ qua công việc của dự án %s: %s", job.project_id, e)
            except Exception:  # noqa: BLE001 - luồng hàng đợi không được chết
                log.exception("Lỗi không mong đợi khi chạy công việc của dự án %s", job.project_id)
            finally:
                with self._lock:
                    self._current = None


manager = JobManager()
