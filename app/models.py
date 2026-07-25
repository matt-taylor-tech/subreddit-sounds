from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Run(Base):
    __tablename__ = "runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="running", nullable=False)
    trigger_type: Mapped[str] = mapped_column(String(32), default="scheduled", nullable=False)
    dry_run: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    added_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    removed_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    low_confidence_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    log: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Which target this run synced. Nullable for pre-multi-target history; no FK
    # so runs remain an immutable audit log even after a target is deleted.
    target_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    target_label: Mapped[str | None] = mapped_column(String(128), nullable=True)


class Target(Base):
    """One playlist to keep in sync, with its own sources and settings.

    The per-playlist "essentials" live here (playlist, subreddits, genre, cap,
    Bandcamp, block-list, schedule). Shared credentials/OAuth and global read
    options (sort, timeframe, min duration, timezone) stay in ``app_settings``.
    """

    __tablename__ = "targets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    playlist_id: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    subreddits: Mapped[str] = mapped_column(Text, default="", nullable=False)
    genre_filter: Mapped[str | None] = mapped_column(String(128), nullable=True)
    cap: Mapped[int] = mapped_column(Integer, default=25, nullable=False)
    bandcamp_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    bandcamp_tags: Mapped[str] = mapped_column(Text, default="", nullable=False)
    bandcamp_enabled_tags: Mapped[str] = mapped_column(Text, default="", nullable=False)
    blocklist_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    blocklist_ids: Mapped[str] = mapped_column(Text, default="", nullable=False)
    last_desired_ids: Mapped[str] = mapped_column(Text, default="", nullable=False)
    sync_hour: Mapped[int] = mapped_column(Integer, default=7, nullable=False)
    sync_minute: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class AppSetting(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="", nullable=False)
    is_secret: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
