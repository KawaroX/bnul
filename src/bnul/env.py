"""Read selected keys from explicitly configured environment/secret files."""
import os
from .client import Error

def env_value(key, fallback=None):
    value = os.environ.get(key)
    if value is not None:
        return value
    path = os.environ.get('BNUL_WATCH_ENV') or os.environ.get('BNUL_CREDENTIAL_ENV')
    if path:
        from dotenv import dotenv_values
        from pathlib import Path
        try:
            with Path(path).expanduser().open() as stream:
                values = dotenv_values(stream=stream, interpolate=False)
        except OSError:
            raise Error('无法读取指定的监控环境文件', 'WATCH_ENV_UNAVAILABLE') from None
        value = values.get(key)
        if value is not None:
            return value
    return fallback
