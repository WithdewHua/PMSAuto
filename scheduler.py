from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore


scheduler = BackgroundScheduler(
    jobstores={"default": SQLAlchemyJobStore(url="sqlite:///jobs.sql")}
)

scheduler.start()
