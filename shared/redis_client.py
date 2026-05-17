import redis.asyncio as aioredis
import os

redis_url = os.getenv("REDIS_URL", "redis://redis:6379/0")
redis_client = aioredis.from_url(redis_url, decode_responses=True)
