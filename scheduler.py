from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore 
from apscheduler.jobstores.memory import MemoryJobStore


scheduler = BackgroundScheduler(
    jobstores={
        "default": MemoryJobStore(),
        "sqlite": SQLAlchemyJobStore(url="sqlite:///jobs.sql"),
    }
)

scheduler.start()
