"""
bot.middleware

Middleware package for authentication, authorization,
rate limiting, logging, and error handling.
"""

from .auth import AuthenticationMiddleware
from .admin import AdminMiddleware
from .throttling import ThrottlingMiddleware
from .logging import LoggingMiddleware
from .errors import ErrorMiddleware

__all__ = [
    "AuthenticationMiddleware",
    "AdminMiddleware",
    "ThrottlingMiddleware",
    "LoggingMiddleware",
    "ErrorMiddleware",
]