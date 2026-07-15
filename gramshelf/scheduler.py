from __future__ import annotations

import threading

from apscheduler.schedulers.background import BackgroundScheduler

from .database import Database
from .sync import SyncManager


class SchedulerController:
    JOB_ID = "instagram-saved-sync"

    def __init__(self, database: Database, sync_manager: SyncManager):
        self.database = database
        self.sync_manager = sync_manager
        self.scheduler = BackgroundScheduler(timezone="UTC", daemon=True)
        self._lock = threading.Lock()

    def start(self) -> None:
        self.scheduler.start()
        self.refresh()

    def refresh(self) -> None:
        with self._lock:
            existing = self.scheduler.get_job(self.JOB_ID)
            if existing is not None:
                self.scheduler.remove_job(self.JOB_ID)
            if not bool(self.database.get_setting("sync_enabled", True)):
                return
            interval = int(self.database.get_setting("sync_interval_minutes", 720))
            interval = min(max(interval, 15), 10080)
            self.scheduler.add_job(
                self._scheduled_sync,
                "interval",
                minutes=interval,
                id=self.JOB_ID,
                coalesce=True,
                max_instances=1,
                misfire_grace_time=300,
            )

    def _scheduled_sync(self) -> None:
        self.sync_manager.start("schedule")

    def next_run_at(self) -> str | None:
        job = self.scheduler.get_job(self.JOB_ID)
        if job is None or job.next_run_time is None:
            return None
        return job.next_run_time.isoformat(timespec="seconds")

    def shutdown(self) -> None:
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)
