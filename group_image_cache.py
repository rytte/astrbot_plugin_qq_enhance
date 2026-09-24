from __future__ import annotations

import asyncio
import hashlib
import io
import re
import secrets
import sqlite3
import time
from contextlib import closing
from pathlib import Path

from PIL import Image as PillowImage

from astrbot.core.utils.media_utils import file_uri_to_path, is_file_uri

GROUP_IMAGE_REF_PATTERN = re.compile(r"gimg_[0-9a-f]{24}")
GROUP_IMAGES_EXTRA = "_qq_enhance_group_images"


class GroupImageCache:
    """Retain downloaded group images within one global byte and time budget.

    Args:
        root: Plugin-owned cache directory.
        max_storage_mb: Global capacity for unique image files in MiB.
        ttl_hours: Lifetime since the image was last received in its scope.
        max_image_mb: Maximum bytes accepted for one inspectable image.
    """

    def __init__(
        self, root: Path, max_storage_mb: int, ttl_hours: int, max_image_mb: int
    ):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.max_bytes = max_storage_mb * 1024 * 1024
        self.ttl_seconds = ttl_hours * 3600
        self.max_image_bytes = max_image_mb * 1024 * 1024
        self._lock = asyncio.Lock()
        self._initialized = False

    async def _run(self, operation):
        """Serialize disk changes, including completion after task cancellation."""
        async with self._lock:
            task = asyncio.create_task(asyncio.to_thread(self._transaction, operation))
            try:
                return await asyncio.shield(task)
            except asyncio.CancelledError:
                await task
                raise

    def _transaction(self, operation):
        with closing(sqlite3.connect(self.root / "index.sqlite3", timeout=10)) as db:
            db.row_factory = sqlite3.Row
            with db:
                db.execute(
                    """CREATE TABLE IF NOT EXISTS images (
                        image_ref TEXT PRIMARY KEY,
                        platform_id TEXT NOT NULL,
                        origin TEXT NOT NULL,
                        conversation_id TEXT NOT NULL,
                        filename TEXT NOT NULL,
                        size_bytes INTEGER NOT NULL,
                        mime_type TEXT NOT NULL,
                        width INTEGER NOT NULL,
                        height INTEGER NOT NULL,
                        received_at REAL NOT NULL,
                        expires_at REAL NOT NULL
                    )"""
                )
                db.execute(
                    "CREATE INDEX IF NOT EXISTS images_scope ON images "
                    "(platform_id, origin, conversation_id, filename)"
                )
                if not self._initialized:
                    filenames = {
                        row[0]
                        for row in db.execute("SELECT DISTINCT filename FROM images")
                    }
                    for path in self.root.glob("blob_*"):
                        if path.is_file() and path.name not in filenames:
                            path.unlink()
                self._prune(db, time.time())
                db.commit()
                self._initialized = True
                return operation(db)

    def _prune(self, db, now):
        """Expire references and enforce capacity without counting shared files twice."""
        expired = db.execute(
            "SELECT DISTINCT filename FROM images WHERE expires_at <= ?", (now,)
        ).fetchall()
        db.execute("DELETE FROM images WHERE expires_at <= ?", (now,))
        for row in expired:
            if not db.execute(
                "SELECT 1 FROM images WHERE filename = ?", (row["filename"],)
            ).fetchone():
                (self.root / row["filename"]).unlink(missing_ok=True)
        blobs = db.execute(
            "SELECT filename, MAX(size_bytes) AS size_bytes FROM images "
            "GROUP BY filename ORDER BY MAX(received_at)"
        ).fetchall()
        total = sum(row["size_bytes"] for row in blobs)
        for row in blobs:
            if total <= self.max_bytes:
                break
            db.execute("DELETE FROM images WHERE filename = ?", (row["filename"],))
            (self.root / row["filename"]).unlink(missing_ok=True)
            total -= row["size_bytes"]

    async def put(
        self, source: str, platform_id: str, origin: str, conversation_id: str
    ):
        """Copy an existing local image once and return a scoped reference.

        Args:
            source: Already downloaded path or file URI; network URLs are rejected.
            platform_id: Source platform instance.
            origin: Source group session, including member isolation if enabled.
            conversation_id: Current conversation ID, or empty before its creation.

        Returns:
            Cached image metadata.

        Raises:
            ValueError: If the source cannot be cached within the configured limits.
            OSError: If local image bytes cannot be read or retained.
        """
        if not source or source.startswith(
            ("http://", "https://", "base64://", "data:")
        ):
            raise ValueError("image has no downloaded local file")
        path = Path(file_uri_to_path(source) if is_file_uri(source) else source)

        def save(db):
            limit = min(self.max_bytes, self.max_image_bytes)
            with path.open("rb") as stream:
                payload = stream.read(limit + 1)
            if len(payload) > limit:
                raise ValueError("image exceeds group cache or inspection limit")
            with PillowImage.open(io.BytesIO(payload)) as image:
                mime_type = PillowImage.MIME.get(image.format, "")
                width, height = image.size
                image.verify()
            if not mime_type.startswith("image/") or width <= 0 or height <= 0:
                raise ValueError("invalid image")
            filename = f"blob_{hashlib.sha256(payload).hexdigest()}"
            existing = db.execute(
                "SELECT image_ref FROM images WHERE platform_id = ? AND origin = ? "
                "AND conversation_id = ? AND filename = ? LIMIT 1",
                (platform_id, origin, conversation_id, filename),
            ).fetchone()
            image_ref = (
                existing["image_ref"] if existing else f"gimg_{secrets.token_hex(12)}"
            )
            now = time.time()
            destination = self.root / filename
            if not destination.is_file():
                # Reserve capacity before copying; image bytes are already validated.
                blobs = db.execute(
                    "SELECT filename, MAX(size_bytes) AS size_bytes FROM images "
                    "GROUP BY filename ORDER BY MAX(received_at)"
                ).fetchall()
                total = sum(row["size_bytes"] for row in blobs)
                for row in blobs:
                    if total + len(payload) <= self.max_bytes:
                        break
                    db.execute(
                        "DELETE FROM images WHERE filename = ?", (row["filename"],)
                    )
                    (self.root / row["filename"]).unlink(missing_ok=True)
                    total -= row["size_bytes"]
                db.commit()
                staging = self.root / f"{filename}.partial"
                try:
                    staging.write_bytes(payload)
                    staging.replace(destination)
                finally:
                    staging.unlink(missing_ok=True)
            db.execute(
                "INSERT OR REPLACE INTO images VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    image_ref,
                    platform_id,
                    origin,
                    conversation_id,
                    filename,
                    len(payload),
                    mime_type,
                    width,
                    height,
                    now,
                    now + self.ttl_seconds,
                ),
            )
            return {"image_ref": image_ref, "width": width, "height": height}

        return await self._run(save)

    async def bind(
        self, image_refs, platform_id: str, origin: str, conversation_id: str
    ):
        """Bind references received before the first conversation to that request.

        Existing conversation bindings are never reassigned.

        Args:
            image_refs: References carried by the assembled request.
            platform_id: Request platform instance.
            origin: Request group session.
            conversation_id: Conversation receiving the referenced group context.
        """
        if not image_refs or not conversation_id:
            return

        def bind_refs(db):
            db.executemany(
                "UPDATE images SET conversation_id = ? WHERE image_ref = ? "
                "AND platform_id = ? AND origin = ? AND conversation_id = ''",
                [(conversation_id, ref, platform_id, origin) for ref in image_refs],
            )

        await self._run(bind_refs)

    async def read(
        self, image_ref: str, platform_id: str, origin: str, conversation_id: str
    ):
        """Read a live scoped image without refreshing its expiry.

        Args:
            image_ref: Reference supplied to the image inspection tool.
            platform_id: Tool caller's platform instance.
            origin: Tool caller's group session.
            conversation_id: Tool caller's current conversation.

        Returns:
            Image bytes and MIME type, or None for an expired or inaccessible reference.
        """
        if not conversation_id:
            return None

        def read_image(db):
            row = db.execute(
                "SELECT filename, mime_type FROM images WHERE image_ref = ? "
                "AND platform_id = ? AND origin = ? AND conversation_id = ?",
                (image_ref, platform_id, origin, conversation_id),
            ).fetchone()
            if row is None:
                return None
            path = self.root / row["filename"]
            if not path.is_file():
                return None
            if path.stat().st_size > self.max_image_bytes:
                raise ValueError("cached image exceeds inspection limit")
            return path.read_bytes(), row["mime_type"]

        return await self._run(read_image)

    async def cleanup(self):
        """Remove expired, evicted, or interrupted cache files."""

        def remove_orphans(db):
            filenames = {
                row[0] for row in db.execute("SELECT DISTINCT filename FROM images")
            }
            for path in self.root.glob("blob_*"):
                if path.is_file() and path.name not in filenames:
                    path.unlink()

        await self._run(remove_orphans)
