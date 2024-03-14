from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.jobstores.memory import MemoryJobStore
from apscheduler.executors.pool import ThreadPoolExecutor


scheduler = BackgroundScheduler(
    jobstores={
        "default": MemoryJobStore(),
        "sqlite": SQLAlchemyJobStore(url="sqlite:///jobs.sql"),
    },
    executors={
        "default": ThreadPoolExecutor(100),
    },
)

scheduler.start()
