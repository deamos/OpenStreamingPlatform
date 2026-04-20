version = "0.9.0"
appDBVersion = 0.70

videoRoot = "/var/www/"

# Build Channel Restream Subprocess Dictionary
restreamSubprocesses = {}

# Build Edge Restream Subprocess Dictionary
activeEdgeNodes = []
edgeRestreamSubprocesses = {}

apiLocation = "http://127.0.0.1"

def get_redis():
    import redis as redis_lib
    try:
        from conf import config
    except Exception:
        import os
        class _C:
            redisHost = os.getenv("OSP_REDIS_HOST", "127.0.0.1")
            redisPort = int(os.getenv("OSP_REDIS_PORT", 6379))
            redisPassword = os.getenv("OSP_REDIS_PASSWORD", "")
        config = _C()

    if not getattr(config, "redisPassword", ""):
        return redis_lib.Redis(
            host=getattr(config, "redisHost", "127.0.0.1"), 
            port=getattr(config, "redisPort", 6379), 
            decode_responses=True
        )
    return redis_lib.Redis(
        host=getattr(config, "redisHost", "127.0.0.1"),
        port=getattr(config, "redisPort", 6379),
        password=config.redisPassword,
        decode_responses=True,
    )
