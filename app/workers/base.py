"""Base background worker with configurable polling interval."""
import asyncio
import logging

logger = logging.getLogger(__name__)


class BaseWorker:
    name: str = "base_worker"
    interval_seconds: int = 60

    async def tick(self) -> None:
        """Override in subclass — called each interval."""
        raise NotImplementedError

    async def run(self) -> None:
        logger.info(f"worker.start", extra={"worker": self.name})
        while True:
            try:
                await self.tick()
            except asyncio.CancelledError:
                logger.info(f"worker.stopped", extra={"worker": self.name})
                return
            except Exception as e:
                logger.error(
                    f"worker.error",
                    extra={"worker": self.name, "error": str(e)},
                    exc_info=True,
                )
            await asyncio.sleep(self.interval_seconds)
