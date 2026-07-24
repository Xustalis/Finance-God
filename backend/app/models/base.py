"""SQLAlchemy ORM 模型基类"""

from datetime import datetime, timezone

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """所有 ORM 模型的基类"""
    pass


def utcnow():
    return datetime.now(timezone.utc)
