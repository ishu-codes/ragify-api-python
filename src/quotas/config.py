"""Quota and rate-limit defaults, overridable via environment variables.

Defaults target the Hobby free tier: 20 credits/month, 1 credit per chat
query, 1 credit per 5 MiB uploaded (min 1 per upload), max 3 workspaces and
20 MiB total storage per user.
"""

from os import getenv


def _env_int(name: str, default: int) -> int:
    try:
        return int(getenv(name, str(default)))
    except ValueError:
        return default


FREE_MONTHLY_CREDITS = _env_int("FREE_MONTHLY_CREDITS", 20)
QUERY_CREDIT_COST = _env_int("QUERY_CREDIT_COST", 1)
UPLOAD_CREDIT_STRIDE_BYTES = _env_int("UPLOAD_CREDIT_STRIDE_BYTES", 5 * 1024 * 1024)
MAX_WORKSPACES = _env_int("MAX_WORKSPACES", 3)
MAX_STORAGE_BYTES = _env_int("MAX_STORAGE_BYTES", 20 * 1024 * 1024)

# Rate-limit buckets: name -> (max requests per window, window seconds).
# Buckets are fixed-window counters stored in PostgreSQL (see rate_limit.py).
RATE_LIMITS: dict[str, tuple[int, int]] = {
    "register": (_env_int("RATE_LIMIT_REGISTER", 2), 3600),
    "register_day": (_env_int("RATE_LIMIT_REGISTER_DAY", 5), 86400),
    "login": (_env_int("RATE_LIMIT_LOGIN", 5), 3600),
    "login_day": (_env_int("RATE_LIMIT_LOGIN_DAY", 20), 86400),
    "api_min": (_env_int("RATE_LIMIT_API_MIN", 50), 60),
    "query_min": (_env_int("RATE_LIMIT_QUERY_MIN", 3), 60),
    "query_day": (_env_int("RATE_LIMIT_QUERY_DAY", 20), 86400),
    "upload_hour": (_env_int("RATE_LIMIT_UPLOAD_HOUR", 3), 3600),
    "upload_day": (_env_int("RATE_LIMIT_UPLOAD_DAY", 8), 86400),
    "workspace_create_hour": (_env_int("RATE_LIMIT_WORKSPACE_CREATE_HOUR", 5), 3600),
    "workspace_create_day": (_env_int("RATE_LIMIT_WORKSPACE_CREATE_DAY", 10), 86400),
}
