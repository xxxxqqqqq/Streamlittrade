"""Transactional outbox dispatcher bridging PostgreSQL jobs to Redis RQ."""

import asyncio
from datetime import UTC,datetime,timedelta
from uuid import UUID
from sqlalchemy import select
from backend.app.db.sync_session import SyncSessionFactory
from backend.app.infrastructure.queue import enqueue_task
from backend.app.models.job import Job,OutboxEvent

def add_outbox(session,job:Job,function_path:str)->OutboxEvent:
    event=OutboxEvent(job_id=job.id,function_path=function_path,status="pending",attempts=0,available_at=datetime.now(UTC))
    session.add(event);return event

def dispatch_pending(limit:int=50)->int:
    dispatched=0
    with SyncSessionFactory() as session:
        events=list(session.scalars(select(OutboxEvent).where(OutboxEvent.status=="pending",OutboxEvent.available_at<=datetime.now(UTC)).order_by(OutboxEvent.created_at).limit(limit).with_for_update(skip_locked=True)).all())
        for event in events:
            try:
                enqueue_task(event.job_id,event.function_path)
                event.status="dispatched";event.dispatched_at=datetime.now(UTC);event.last_error=None;dispatched+=1
            except Exception as exc:
                event.attempts+=1;event.last_error=str(exc)[:1000];event.available_at=datetime.now(UTC)+timedelta(seconds=min(300,2**event.attempts))
        session.commit()
    return dispatched

def recover_expired_jobs()->int:
    """Return expired running jobs to the outbox until their retry budget is spent."""
    recovered=0
    with SyncSessionFactory() as session:
        jobs=list(session.scalars(select(Job).where(Job.status=="running",Job.lease_expires_at.is_not(None),Job.lease_expires_at<datetime.now(UTC))).all())
        for job in jobs:
            if job.attempt>=job.max_attempts:
                job.status="failed";job.error_message="Worker lease expired and retry budget was exhausted";job.completed_at=datetime.now(UTC)
            else:
                job.status="queued";job.started_at=None;job.lease_expires_at=None
                existing=session.scalar(select(OutboxEvent).where(OutboxEvent.job_id==job.id))
                if existing:existing.status="pending";existing.available_at=datetime.now(UTC);existing.dispatched_at=None
            recovered+=1
        session.commit()
    return recovered

async def outbox_loop(stop:asyncio.Event)->None:
    while not stop.is_set():
        await asyncio.to_thread(dispatch_pending)
        await asyncio.to_thread(recover_expired_jobs)
        try:await asyncio.wait_for(stop.wait(),timeout=2)
        except TimeoutError:pass
