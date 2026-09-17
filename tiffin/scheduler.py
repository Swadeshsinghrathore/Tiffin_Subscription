"""
TiffinBox Daily 9:00 AM Background Notification Scheduler
Monitors system clock and automatically triggers dispatch_daily_delivery_notifications()
every morning at 9:00 AM local time.
"""

from datetime import date, datetime
import logging
import threading
import time
from typing import Optional

logger = logging.getLogger(__name__)

_scheduler_thread: Optional[threading.Thread] = None
_stop_event = threading.Event()
_last_dispatched_date: Optional[date] = None
_target_hour = 9  # 9:00 AM daily
_target_minute = 0


def _scheduler_loop(app):
    global _last_dispatched_date
    logger.info("Notification scheduler daemon started (Target: %02d:%02d daily).", _target_hour, _target_minute)

    while not _stop_event.is_set():
        now = datetime.now()

        # Check if it's 9:00 AM or later today and we haven't dispatched yet today
        if now.hour == _target_hour and now.minute >= _target_minute:
            if _last_dispatched_date != now.date():
                logger.info("Triggering 9:00 AM automatic delivery notifications for %s...", now.date())
                try:
                    with app.app_context():
                        from tiffin.notifications import dispatch_daily_delivery_notifications
                        result = dispatch_daily_delivery_notifications(on_date=now.date())
                        logger.info("9:00 AM notification dispatch result: %s", result)
                    _last_dispatched_date = now.date()
                except Exception as e:
                    logger.exception("Error running 9:00 AM notification job: %s", e)

        # Sleep 30 seconds before next check
        _stop_event.wait(30)


def start_scheduler(app) -> None:
    """Start background scheduler daemon thread if not already running."""
    global _scheduler_thread
    if _scheduler_thread is not None and _scheduler_thread.is_alive():
        return

    _stop_event.clear()
    _scheduler_thread = threading.Thread(
        target=_scheduler_loop,
        args=(app,),
        name="TiffinNotificationScheduler",
        daemon=True,
    )
    _scheduler_thread.start()


def stop_scheduler() -> None:
    """Signal scheduler thread to stop."""
    _stop_event.set()


def get_scheduler_info() -> dict:
    """Return scheduler health and last run information."""
    is_running = _scheduler_thread is not None and _scheduler_thread.is_alive()
    return {
        "running": is_running,
        "target_time": f"{_target_hour:02d}:{_target_minute:02d} AM",
        "last_dispatched_date": _last_dispatched_date.isoformat() if _last_dispatched_date else None,
        "current_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
