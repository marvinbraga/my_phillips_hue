"""Asyncio schedule poller started from FastAPI lifespan."""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Optional

from marvin_hue.logging_config import get_logger
from marvin_hue.services.schedule_service import ScheduleService

logger = get_logger("services.schedule_runner")

DEFAULT_POLL_SECONDS = 30.0


class ScheduleRunner:
    """Background loop that calls ScheduleService.tick on an interval."""

    def __init__(
        self,
        service: ScheduleService,
        *,
        poll_seconds: float = DEFAULT_POLL_SECONDS,
    ) -> None:
        if poll_seconds <= 0:
            raise ValueError("poll_seconds must be > 0")
        self._service = service
        self._poll_seconds = poll_seconds
        self._task: Optional[asyncio.Task[None]] = None
        self._stopped = asyncio.Event()

    @property
    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def start(self) -> None:
        if self.is_running:
            return
        self._stopped.clear()
        self._task = asyncio.create_task(self._loop(), name="schedule-runner")
        logger.info(f"ScheduleRunner started poll_seconds={self._poll_seconds}")

    async def stop(self) -> None:
        self._stopped.set()
        task = self._task
        self._task = None
        if task is None:
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        logger.info("ScheduleRunner stopped")

    async def _loop(self) -> None:
        while not self._stopped.is_set():
            try:
                local_now = datetime.now().astimezone()
                results = await self._service.tick(local_now)
                if results:
                    logger.info(f"Schedule tick fired {len(results)} action(s)")
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.exception(f"schedule tick failed: {exc}")
            try:
                await asyncio.wait_for(
                    self._stopped.wait(), timeout=self._poll_seconds
                )
                break
            except asyncio.TimeoutError:
                continue
