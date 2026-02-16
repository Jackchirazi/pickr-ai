"""
Pickr AI - Background Job Processor (v2)
Polls for queued jobs and processes them via the pipeline.
Designed to run as a separate worker process alongside the API server.
"""
import logging
import time
import signal
import sys
from pickr.models import SessionLocal, Job, JobStatus, init_db
from pickr.pipeline import PickrPipeline
from pickr.config import SCHEMA_VERSION

logger = logging.getLogger(__name__)

# Graceful shutdown flag
_shutdown = False


def _handle_signal(signum, frame):
    global _shutdown
    logger.info(f"Received signal {signum}. Shutting down gracefully...")
    _shutdown = True


def run_worker(poll_interval: int = 30):
    """
    Worker loop: poll for queued jobs, process them via the pipeline.

    This replaces APScheduler with a simpler poll-based approach
    that works well with PostgreSQL and Docker.

    Args:
        poll_interval: Seconds between poll cycles (default: 30)
    """
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    pipeline = PickrPipeline()
    pipeline.initialize()

    logger.info(
        f"Pickr AI Worker started. Schema: {SCHEMA_VERSION}. "
        f"Polling every {poll_interval}s."
    )

    while not _shutdown:
        db = SessionLocal()
        try:
            # Count queued jobs
            queued = db.query(Job).filter(
                Job.status == JobStatus.QUEUED.value
            ).count()

            if queued > 0:
                logger.info(f"Found {queued} queued jobs. Processing...")
                results = pipeline.process_queued_jobs(db)
                logger.info(f"Processing results: {results}")
            else:
                logger.debug("No queued jobs. Sleeping...")

        except Exception as e:
            logger.error(f"Worker error: {e}", exc_info=True)
        finally:
            db.close()

        # Sleep in small increments to allow graceful shutdown
        for _ in range(poll_interval):
            if _shutdown:
                break
            time.sleep(1)

    logger.info("Worker shutdown complete.")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    interval = int(sys.argv[1]) if len(sys.argv) > 1 else 30
    run_worker(poll_interval=interval)
