from celery import Celery
from app.config import settings

celery = Celery("marches", broker=settings.redis_url, backend=settings.redis_url)
celery.conf.task_default_queue = "default"
celery.autodiscover_tasks(["app"])
