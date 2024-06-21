from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.jobstores.memory import MemoryJobStore
from apscheduler.executors.pool import ThreadPoolExecutor
from utils import Singleton


class Scheduler(metaclass=Singleton):
    def __init__(self) -> None:
        self.jobstores = {
            "default": MemoryJobStore(),
        }
        self.executors = {
            "default": ThreadPoolExecutor(100)
        }
        self.scheduler = BackgroundScheduler(jobstores=self.jobstores, executors=self.executors)

        self.start()

    def start(self):
        self.scheduler.start()

    def shutdown(self):
        self.scheduler.shutdown()

    def add_jobstore(self, *args, **kwargs):
        self.scheduler.add_jobstore(*args, **kwargs)

    def add_job(self, *args, **kwargs):
        self.scheduler.add_job(*args, **kwargs)

