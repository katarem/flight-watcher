"""Planificador interno (sustituye al cron externo). La hora se cambia desde Ajustes.

Dos tareas: la ronda de precios (a las horas de Ajustes) y, cada lunes, la revalidación de la cobertura
de rutas (`coverage.revalidate`), que avisa si una ruta de temporada se abre o se cierra.
"""
from __future__ import annotations

import logging
import re
import threading
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from . import checker, coverage, db

log = logging.getLogger("scheduler")
scheduler = BackgroundScheduler()
_HOURS = re.compile(r"^\d{1,2}(,\d{1,2})*$")


def valid_hours(value: str) -> bool:
    return bool(_HOURS.match(value)) and all(0 <= int(h) <= 23 for h in value.split(","))


def reschedule():
    s = db.get_settings()
    try:
        tz = ZoneInfo(s["timezone"])
    except Exception:  # noqa: BLE001
        tz = ZoneInfo("UTC")
    hours = s["schedule_hours"] if valid_hours(s["schedule_hours"]) else "8"
    trigger = CronTrigger(hour=hours, minute=int(s["schedule_minute"]), timezone=tz)
    scheduler.add_job(
        checker.run_checks, trigger, id="daily", replace_existing=True,
        coalesce=True, misfire_grace_time=3600, kwargs={"trigger": "cron"},
    )
    # La revalidación semanal, antes de la primera ronda del lunes para que ya use la cobertura nueva.
    scheduler.add_job(
        coverage.revalidate, CronTrigger(day_of_week="mon", hour=5, minute=10, timezone=tz), id="coverage",
        replace_existing=True, coalesce=True, misfire_grace_time=6 * 3600, kwargs={"trigger": "cron"},
    )
    log.info("Comprobación programada a las %s:%s (%s)", hours, s["schedule_minute"], tz)


def start():
    scheduler.start()
    reschedule()


def stop():
    if scheduler.running:
        scheduler.shutdown(wait=False)


def next_run():
    job = scheduler.get_job("daily")
    return job.next_run_time if job else None


def run_now(watch_id: int | None = None, user_id: int | None = None) -> bool:
    """Lanza una ronda en segundo plano (de una vigilancia, de un usuario o de todos). False si ya hay una."""
    if checker.is_running():
        return False
    threading.Thread(
        target=checker.run_checks, kwargs={"watch_id": watch_id, "trigger": "manual", "user_id": user_id}, daemon=True
    ).start()
    return True


def revalidate_now() -> bool:
    """Revalida ya la cobertura de todas las vigilancias (en segundo plano)."""
    threading.Thread(target=coverage.revalidate, kwargs={"trigger": "manual"}, daemon=True).start()
    return True
