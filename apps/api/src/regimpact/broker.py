"""Dramatiq broker configuration shared by API-side dispatchers and workers."""

import dramatiq
from dramatiq.brokers.redis import RedisBroker

from .config import get_settings

broker = RedisBroker(url=get_settings().redis_url)
dramatiq.set_broker(broker)
