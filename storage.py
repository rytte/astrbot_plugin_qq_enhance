from __future__ import annotations

import asyncio
import hashlib
import json
import sqlite3
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any


class Storage:
    """Persist confirmations, audits, events, requests, and media references.

    Args:
        database_path: SQLite database path owned by this plugin.
    """

    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path

    async def initialize(self) -> None:
        """Create the database schema when it does not exist."""

        self.database_path.parent.mkdir(parents=True, exist_ok=True)

        def initialize_sync() -> None:
            with sqlite3.connect(self.database_path, timeout=10) as connection:
                connection.executescript(
                    """
                    PRAGMA journal_mode=WAL;
                    PRAGMA foreign_keys=ON;
                    CREATE TABLE IF NOT EXISTS pending_actions (
                        pending_id TEXT PRIMARY KEY,
                        caller_id TEXT NOT NULL,
                        session_id TEXT NOT NULL,
                        platform_id TEXT NOT NULL,
                        operation_id TEXT NOT NULL,
                        action TEXT,
                        params_json TEXT NOT NULL,
                        params_hash TEXT NOT NULL,
                        target_kind TEXT NOT NULL,
                        target_id TEXT NOT NULL,
                        summary TEXT NOT NULL,
                        created_at INTEGER NOT NULL,
                        expires_at INTEGER NOT NULL,
                        status TEXT NOT NULL CHECK (
                            status IN ('pending', 'executing', 'completed', 'cancelled')
                        )
                    );
                    CREATE INDEX IF NOT EXISTS idx_pending_identity
                        ON pending_actions(caller_id, session_id, status, expires_at);

                    CREATE TABLE IF NOT EXISTS audit_logs (
                        audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
                        created_at INTEGER NOT NULL,
                        operation_id TEXT NOT NULL,
                        caller_id TEXT NOT NULL,
                        session_id TEXT NOT NULL,
                        platform_id TEXT NOT NULL,
                        target_kind TEXT NOT NULL,
                        target_id TEXT NOT NULL,
                        risk TEXT NOT NULL,
                        decision TEXT NOT NULL,
                        result_code TEXT NOT NULL,
                        pending_id TEXT NOT NULL,
                        params_hash TEXT NOT NULL,
                        duration_ms INTEGER NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS idx_audit_created
                        ON audit_logs(created_at DESC);

                    CREATE TABLE IF NOT EXISTS events (
                        event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                        created_at INTEGER NOT NULL,
                        platform_id TEXT NOT NULL,
                        post_type TEXT NOT NULL,
                        event_type TEXT NOT NULL,
                        sub_type TEXT NOT NULL,
                        actor_id TEXT NOT NULL,
                        group_id TEXT NOT NULL,
                        event_key TEXT NOT NULL,
                        data_json TEXT NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS idx_events_created
                        ON events(created_at DESC);
                    CREATE INDEX IF NOT EXISTS idx_events_key
                        ON events(event_key);

                    CREATE TABLE IF NOT EXISTS requests (
                        request_id INTEGER PRIMARY KEY AUTOINCREMENT,
                        created_at INTEGER NOT NULL,
                        platform_id TEXT NOT NULL,
                        request_type TEXT NOT NULL,
                        sub_type TEXT NOT NULL,
                        actor_id TEXT NOT NULL,
                        group_id TEXT NOT NULL,
                        flag TEXT NOT NULL,
                        comment_hash TEXT NOT NULL,
                        status TEXT NOT NULL CHECK (
                            status IN ('pending', 'approved', 'rejected')
                        )
                    );
                    CREATE INDEX IF NOT EXISTS idx_requests_lookup
                        ON requests(request_type, status, created_at DESC);

                    CREATE TABLE IF NOT EXISTS media_refs (
                        media_ref TEXT PRIMARY KEY,
                        owner_id TEXT NOT NULL,
                        source TEXT NOT NULL,
                        path TEXT NOT NULL,
                        created_at INTEGER NOT NULL,
                        expires_at INTEGER NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS idx_media_expiry
                        ON media_refs(expires_at);

                    CREATE TABLE IF NOT EXISTS context_images (
                        image_ref TEXT PRIMARY KEY,
                        platform_id TEXT NOT NULL,
                        unified_msg_origin TEXT NOT NULL,
                        conversation_id TEXT NOT NULL,
                        path TEXT NOT NULL,
                        mime_type TEXT NOT NULL,
                        width INTEGER NOT NULL,
                        height INTEGER NOT NULL,
                        size_bytes INTEGER NOT NULL,
                        created_at INTEGER NOT NULL,
                        last_accessed_at INTEGER NOT NULL,
                        orphaned_at INTEGER
                    );
                    CREATE INDEX IF NOT EXISTS idx_context_images_scope
                        ON context_images(
                            platform_id, unified_msg_origin, conversation_id
                        );
                    CREATE INDEX IF NOT EXISTS idx_context_images_orphaned
                        ON context_images(orphaned_at);
                    CREATE INDEX IF NOT EXISTS idx_context_images_created
                        ON context_images(created_at);
                    """
                )
                columns = {
                    row[1]
                    for row in connection.execute(
                        "PRAGMA table_info(context_images)"
                    ).fetchall()
                }
                # Rebuild the development schema once without obsolete provenance.
                if {"source_message_id", "source_kind"} & columns:
                    connection.execute("BEGIN IMMEDIATE")
                    connection.execute(
                        """
                        CREATE TABLE context_images_rebuilt (
                            image_ref TEXT PRIMARY KEY,
                            platform_id TEXT NOT NULL,
                            unified_msg_origin TEXT NOT NULL,
                            conversation_id TEXT NOT NULL,
                            path TEXT NOT NULL,
                            mime_type TEXT NOT NULL,
                            width INTEGER NOT NULL,
                            height INTEGER NOT NULL,
                            size_bytes INTEGER NOT NULL,
                            created_at INTEGER NOT NULL,
                            last_accessed_at INTEGER NOT NULL,
                            orphaned_at INTEGER
                        )
                        """
                    )
                    connection.execute(
                        """
                        INSERT INTO context_images_rebuilt (
                            image_ref, platform_id, unified_msg_origin,
                            conversation_id, path, mime_type, width, height,
                            size_bytes, created_at, last_accessed_at, orphaned_at
                        )
                        SELECT
                            image_ref, platform_id, unified_msg_origin,
                            conversation_id, path, mime_type, width, height,
                            size_bytes, created_at, last_accessed_at, orphaned_at
                        FROM context_images
                        """
                    )
                    connection.execute("DROP TABLE context_images")
                    connection.execute(
                        "ALTER TABLE context_images_rebuilt RENAME TO context_images"
                    )
                    connection.execute(
                        """
                        CREATE INDEX idx_context_images_scope
                        ON context_images(
                            platform_id, unified_msg_origin, conversation_id
                        )
                        """
                    )
                    connection.execute(
                        """
                        CREATE INDEX idx_context_images_orphaned
                        ON context_images(orphaned_at)
                        """
                    )
                    connection.execute(
                        """
                        CREATE INDEX idx_context_images_created
                        ON context_images(created_at)
                        """
                    )
                    connection.commit()

        await asyncio.to_thread(initialize_sync)

    async def create_pending(self, record: dict[str, Any]) -> None:
        """Persist a pending operation with exact normalized parameters.

        Args:
            record: Fully validated pending operation fields.
        """

        params_json = json.dumps(
            record["params"], sort_keys=True, separators=(",", ":"), ensure_ascii=False
        )
        params_hash = hashlib.sha256(params_json.encode()).hexdigest()

        def create_sync() -> None:
            with sqlite3.connect(self.database_path, timeout=10) as connection:
                connection.execute(
                    """
                    INSERT INTO pending_actions (
                        pending_id, caller_id, session_id, platform_id,
                        operation_id, action, params_json, params_hash,
                        target_kind, target_id, summary, created_at,
                        expires_at, status
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending')
                    """,
                    (
                        record["pending_id"],
                        record["caller_id"],
                        record["session_id"],
                        record["platform_id"],
                        record["operation_id"],
                        record.get("action"),
                        params_json,
                        params_hash,
                        record["target_kind"],
                        record["target_id"],
                        record["summary"],
                        record["created_at"],
                        record["expires_at"],
                    ),
                )

        await asyncio.to_thread(create_sync)

    async def claim_pending(
        self, pending_id: str, caller_id: str, session_id: str, platform_id: str
    ) -> dict[str, Any] | None:
        """Atomically claim a pending operation for one-time execution.

        Args:
            pending_id: Pending operation identifier.
            caller_id: Confirming real user ID.
            session_id: Confirming conversation identifier.
            platform_id: Confirming platform instance ID.

        Returns:
            Claimed record, or ``None`` when binding, status, or expiry fails.
        """

        now = int(time.time())

        def claim_sync() -> dict[str, Any] | None:
            with sqlite3.connect(self.database_path, timeout=10) as connection:
                connection.row_factory = sqlite3.Row
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute(
                    """
                    SELECT * FROM pending_actions
                    WHERE pending_id = ? AND caller_id = ? AND session_id = ?
                      AND platform_id = ? AND status = 'pending' AND expires_at >= ?
                    """,
                    (pending_id, caller_id, session_id, platform_id, now),
                ).fetchone()
                if row is None:
                    connection.rollback()
                    return None
                updated = connection.execute(
                    """
                    UPDATE pending_actions SET status = 'executing'
                    WHERE pending_id = ? AND status = 'pending'
                    """,
                    (pending_id,),
                ).rowcount
                if updated != 1:
                    connection.rollback()
                    return None
                connection.commit()
                result = dict(row)
                result["params"] = json.loads(result.pop("params_json"))
                return result

        return await asyncio.to_thread(claim_sync)

    async def finish_pending(self, pending_id: str) -> None:
        """Mark a claimed pending operation as consumed.

        Args:
            pending_id: Pending operation identifier.
        """

        def finish_sync() -> None:
            with sqlite3.connect(self.database_path, timeout=10) as connection:
                connection.execute(
                    """
                    UPDATE pending_actions SET status = 'completed'
                    WHERE pending_id = ? AND status = 'executing'
                    """,
                    (pending_id,),
                )

        await asyncio.to_thread(finish_sync)

    async def cancel_pending(
        self, pending_id: str, caller_id: str, session_id: str, platform_id: str
    ) -> bool:
        """Cancel a pending operation bound to the current user and session.

        Args:
            pending_id: Pending operation identifier.
            caller_id: Cancelling user ID.
            session_id: Cancelling conversation identifier.
            platform_id: Cancelling platform instance ID.

        Returns:
            Whether a pending record was cancelled.
        """

        def cancel_sync() -> bool:
            with sqlite3.connect(self.database_path, timeout=10) as connection:
                updated = connection.execute(
                    """
                    UPDATE pending_actions SET status = 'cancelled'
                    WHERE pending_id = ? AND caller_id = ? AND session_id = ?
                      AND platform_id = ? AND status = 'pending'
                    """,
                    (pending_id, caller_id, session_id, platform_id),
                ).rowcount
                return updated == 1

        return await asyncio.to_thread(cancel_sync)

    async def list_pending(
        self, caller_id: str, session_id: str, platform_id: str, limit: int = 20
    ) -> list[dict[str, Any]]:
        """List live confirmations for the current user and session.

        Args:
            caller_id: Current user ID.
            session_id: Current conversation identifier.
            platform_id: Current platform instance ID.
            limit: Maximum result count.

        Returns:
            Pending confirmation summaries without raw parameters.
        """

        now = int(time.time())

        def list_sync() -> list[dict[str, Any]]:
            with sqlite3.connect(self.database_path, timeout=10) as connection:
                connection.row_factory = sqlite3.Row
                rows = connection.execute(
                    """
                    SELECT pending_id, operation_id, target_kind, target_id,
                           summary, created_at, expires_at
                    FROM pending_actions
                    WHERE caller_id = ? AND session_id = ? AND platform_id = ?
                      AND status = 'pending' AND expires_at >= ?
                    ORDER BY created_at DESC LIMIT ?
                    """,
                    (caller_id, session_id, platform_id, now, limit),
                ).fetchall()
                return [dict(row) for row in rows]

        return await asyncio.to_thread(list_sync)

    async def list_live_pending(self, limit: int = 20) -> list[dict[str, Any]]:
        """List live confirmations for the authenticated dashboard page.

        Args:
            limit: Maximum result count.

        Returns:
            Pending confirmation metadata without raw action parameters.
        """

        now = int(time.time())

        def list_sync() -> list[dict[str, Any]]:
            with sqlite3.connect(self.database_path, timeout=10) as connection:
                connection.row_factory = sqlite3.Row
                rows = connection.execute(
                    """
                    SELECT pending_id, caller_id, platform_id, operation_id,
                           target_kind, target_id, summary, created_at, expires_at
                    FROM pending_actions
                    WHERE status = 'pending' AND expires_at >= ?
                    ORDER BY created_at DESC LIMIT ?
                    """,
                    (now, limit),
                ).fetchall()
                return [dict(row) for row in rows]

        return await asyncio.to_thread(list_sync)

    async def add_audit(self, record: dict[str, Any]) -> None:
        """Append a metadata-only audit record.

        Args:
            record: Sanitized audit fields without message bodies or file paths.
        """

        def add_sync() -> None:
            with sqlite3.connect(self.database_path, timeout=10) as connection:
                connection.execute(
                    """
                    INSERT INTO audit_logs (
                        created_at, operation_id, caller_id, session_id,
                        platform_id, target_kind, target_id, risk, decision,
                        result_code, pending_id, params_hash, duration_ms
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        record["created_at"],
                        record["operation_id"],
                        record["caller_id"],
                        record["session_id"],
                        record["platform_id"],
                        record["target_kind"],
                        record["target_id"],
                        record["risk"],
                        record["decision"],
                        record["result_code"],
                        record.get("pending_id", ""),
                        record["params_hash"],
                        record.get("duration_ms", 0),
                    ),
                )

        await asyncio.to_thread(add_sync)

    async def list_audit(self, limit: int = 20) -> list[dict[str, Any]]:
        """Return recent metadata-only audit records.

        Args:
            limit: Maximum result count.

        Returns:
            Recent audit rows.
        """

        def list_sync() -> list[dict[str, Any]]:
            with sqlite3.connect(self.database_path, timeout=10) as connection:
                connection.row_factory = sqlite3.Row
                rows = connection.execute(
                    """
                    SELECT audit_id, created_at, operation_id, caller_id,
                           session_id, platform_id, target_kind, target_id,
                           risk, decision, result_code, pending_id, duration_ms
                    FROM audit_logs ORDER BY created_at DESC LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
                return [dict(row) for row in rows]

        return await asyncio.to_thread(list_sync)

    async def add_event(self, record: dict[str, Any]) -> int | None:
        """Persist one normalized OneBot request or notice event.

        Args:
            record: Normalized event metadata.

        Returns:
            The request ID for a request, the event ID for a notice, or ``None``
            when the same event was already stored.
        """

        data_json = json.dumps(
            record.get("data", {}), sort_keys=True, ensure_ascii=False
        )

        def add_sync() -> int | None:
            with sqlite3.connect(self.database_path, timeout=10) as connection:
                connection.execute("BEGIN IMMEDIATE")
                duplicate = connection.execute(
                    "SELECT 1 FROM events WHERE event_key = ? LIMIT 1",
                    (record["event_key"],),
                ).fetchone()
                if duplicate:
                    return None
                event_cursor = connection.execute(
                    """
                    INSERT INTO events (
                        created_at, platform_id, post_type, event_type, sub_type,
                        actor_id, group_id, event_key, data_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        record["created_at"],
                        record["platform_id"],
                        record["post_type"],
                        record["event_type"],
                        record["sub_type"],
                        record["actor_id"],
                        record["group_id"],
                        record["event_key"],
                        data_json,
                    ),
                )
                if record["post_type"] == "request":
                    request_cursor = connection.execute(
                        """
                        INSERT INTO requests (
                            created_at, platform_id, request_type, sub_type,
                            actor_id, group_id, flag, comment_hash, status
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending')
                        """,
                        (
                            record["created_at"],
                            record["platform_id"],
                            record["event_type"],
                            record["sub_type"],
                            record["actor_id"],
                            record["group_id"],
                            record.get("flag", ""),
                            record.get("comment_hash", ""),
                        ),
                    )
                    return int(request_cursor.lastrowid)
                return int(event_cursor.lastrowid)

        return await asyncio.to_thread(add_sync)

    async def list_requests(
        self, request_type: str, status: str = "pending", limit: int = 50
    ) -> list[dict[str, Any]]:
        """List normalized friend or group requests.

        Args:
            request_type: OneBot request type, ``friend`` or ``group``.
            status: Stored processing status.
            limit: Maximum result count.

        Returns:
            Matching request metadata.
        """

        def list_sync() -> list[dict[str, Any]]:
            with sqlite3.connect(self.database_path, timeout=10) as connection:
                connection.row_factory = sqlite3.Row
                rows = connection.execute(
                    """
                    SELECT request_id, created_at, platform_id, request_type,
                           sub_type, actor_id, group_id, flag, status
                    FROM requests
                    WHERE request_type = ? AND status = ?
                    ORDER BY created_at DESC LIMIT ?
                    """,
                    (request_type, status, limit),
                ).fetchall()
                return [dict(row) for row in rows]

        return await asyncio.to_thread(list_sync)

    async def get_pending_request(
        self, request_id: int, platform_id: str
    ) -> dict[str, Any] | None:
        """Return one pending request scoped to the current platform instance.

        Args:
            request_id: Plugin-local request identifier shown in notifications.
            platform_id: Current AstrBot platform instance identifier.

        Returns:
            Pending request metadata including its internal flag, or ``None``.
        """

        def get_sync() -> dict[str, Any] | None:
            with sqlite3.connect(self.database_path, timeout=10) as connection:
                connection.row_factory = sqlite3.Row
                row = connection.execute(
                    """
                    SELECT request_id, created_at, platform_id, request_type,
                           sub_type, actor_id, group_id, flag, status
                    FROM requests
                    WHERE request_id = ? AND platform_id = ? AND status = 'pending'
                    """,
                    (request_id, platform_id),
                ).fetchone()
                return dict(row) if row else None

        return await asyncio.to_thread(get_sync)

    async def update_request(self, flag: str, status: str) -> None:
        """Mark all matching captured requests as processed.

        Args:
            flag: OneBot request flag.
            status: New ``approved`` or ``rejected`` status.
        """

        if status not in {"approved", "rejected"}:
            raise ValueError("invalid request status")

        def update_sync() -> None:
            with sqlite3.connect(self.database_path, timeout=10) as connection:
                connection.execute(
                    "UPDATE requests SET status = ? WHERE flag = ? AND status = 'pending'",
                    (status, flag),
                )

        await asyncio.to_thread(update_sync)

    async def add_media_ref(
        self,
        media_ref: str,
        owner_id: str,
        source: str,
        path: Path,
        expires_at: int,
    ) -> None:
        """Persist an opaque reference to a controlled local media file.

        Args:
            media_ref: Opaque reference shown to the model.
            owner_id: User allowed to resolve the reference.
            source: Non-sensitive source category.
            path: Internal absolute file path.
            expires_at: Unix expiry timestamp.
        """

        def add_sync() -> None:
            with sqlite3.connect(self.database_path, timeout=10) as connection:
                connection.execute(
                    """
                    INSERT INTO media_refs (
                        media_ref, owner_id, source, path, created_at, expires_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        media_ref,
                        owner_id,
                        source,
                        str(path),
                        int(time.time()),
                        expires_at,
                    ),
                )

        await asyncio.to_thread(add_sync)

    async def resolve_media_ref(self, media_ref: str, owner_id: str) -> Path | None:
        """Resolve an unexpired media reference owned by the caller.

        Args:
            media_ref: Opaque media reference.
            owner_id: Current caller ID.

        Returns:
            Stored path, or ``None`` when unavailable.
        """

        now = int(time.time())

        def resolve_sync() -> Path | None:
            with sqlite3.connect(self.database_path, timeout=10) as connection:
                row = connection.execute(
                    """
                    SELECT path FROM media_refs
                    WHERE media_ref = ? AND owner_id = ? AND expires_at >= ?
                    """,
                    (media_ref, owner_id, now),
                ).fetchone()
                return Path(row[0]) if row else None

        return await asyncio.to_thread(resolve_sync)

    async def add_context_images(
        self,
        records: list[dict[str, Any]],
        max_storage_bytes: int,
    ) -> list[Path] | None:
        """Atomically evict oldest local-day buckets and persist image records.

        Args:
            records: Fully validated image metadata records.
            max_storage_bytes: Maximum bytes allowed for all context images.

        Returns:
            Evicted file paths, or ``None`` when the batch alone exceeds capacity.
        """

        def add_sync() -> list[Path] | None:
            with sqlite3.connect(self.database_path, timeout=10) as connection:
                connection.execute("BEGIN IMMEDIATE")
                stored_bytes = int(
                    connection.execute(
                        "SELECT COALESCE(SUM(size_bytes), 0) FROM context_images"
                    ).fetchone()[0]
                )
                incoming_bytes = sum(int(record["size_bytes"]) for record in records)
                if incoming_bytes > max_storage_bytes:
                    connection.rollback()
                    return None
                evicted_paths: list[Path] = []
                while stored_bytes + incoming_bytes > max_storage_bytes:
                    oldest_row = connection.execute(
                        "SELECT MIN(created_at) FROM context_images"
                    ).fetchone()
                    oldest_at = oldest_row[0] if oldest_row else None
                    if oldest_at is None:
                        raise RuntimeError("context image capacity accounting failed")
                    oldest_day = datetime.fromtimestamp(int(oldest_at)).date()
                    next_day_start = int(
                        datetime.combine(
                            oldest_day + timedelta(days=1), datetime.min.time()
                        ).timestamp()
                    )
                    day_rows = connection.execute(
                        """
                        SELECT path, size_bytes FROM context_images
                        WHERE created_at < ?
                        """,
                        (next_day_start,),
                    ).fetchall()
                    if not day_rows:
                        raise RuntimeError("oldest context image day was empty")
                    connection.execute(
                        "DELETE FROM context_images WHERE created_at < ?",
                        (next_day_start,),
                    )
                    stored_bytes -= sum(int(row[1]) for row in day_rows)
                    evicted_paths.extend(Path(row[0]) for row in day_rows)
                connection.executemany(
                    """
                    INSERT INTO context_images (
                        image_ref, platform_id, unified_msg_origin,
                        conversation_id, path, mime_type, width, height,
                        size_bytes, created_at, last_accessed_at, orphaned_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
                    """,
                    [
                        (
                            record["image_ref"],
                            record["platform_id"],
                            record["unified_msg_origin"],
                            record["conversation_id"],
                            str(record["path"]),
                            record["mime_type"],
                            record["width"],
                            record["height"],
                            record["size_bytes"],
                            record["created_at"],
                            record["last_accessed_at"],
                        )
                        for record in records
                    ],
                )
                connection.commit()
                return evicted_paths

        return await asyncio.to_thread(add_sync)

    async def resolve_context_image(
        self,
        image_ref: str,
        platform_id: str,
        unified_msg_origin: str,
        conversation_id: str,
    ) -> dict[str, Any] | None:
        """Resolve one image only inside its originating conversation scope.

        Args:
            image_ref: Opaque persistent image identifier.
            platform_id: Current platform instance ID.
            unified_msg_origin: Current AstrBot session origin.
            conversation_id: Current AstrBot conversation ID.

        Returns:
            Stored metadata, or ``None`` when the reference is out of scope.
        """

        now = int(time.time())

        def resolve_sync() -> dict[str, Any] | None:
            with sqlite3.connect(self.database_path, timeout=10) as connection:
                connection.row_factory = sqlite3.Row
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute(
                    """
                    SELECT * FROM context_images
                    WHERE image_ref = ? AND platform_id = ?
                      AND unified_msg_origin = ? AND conversation_id = ?
                    """,
                    (
                        image_ref,
                        platform_id,
                        unified_msg_origin,
                        conversation_id,
                    ),
                ).fetchone()
                if row is None:
                    connection.rollback()
                    return None
                connection.execute(
                    """
                    UPDATE context_images SET last_accessed_at = ?
                    WHERE image_ref = ?
                    """,
                    (now, image_ref),
                )
                connection.commit()
                result = dict(row)
                result["last_accessed_at"] = now
                return result

        return await asyncio.to_thread(resolve_sync)

    async def list_context_images(self) -> list[dict[str, Any]]:
        """List context image metadata for lifecycle reconciliation.

        Returns:
            All stored context image records.
        """

        def list_sync() -> list[dict[str, Any]]:
            with sqlite3.connect(self.database_path, timeout=10) as connection:
                connection.row_factory = sqlite3.Row
                rows = connection.execute(
                    "SELECT * FROM context_images ORDER BY created_at"
                ).fetchall()
                return [dict(row) for row in rows]

        return await asyncio.to_thread(list_sync)

    async def reconcile_context_images(
        self,
        liveness: dict[str, bool],
        checked_at: int,
        orphan_cutoff_exclusive: int,
        retention_cutoff_exclusive: int | None,
    ) -> list[Path]:
        """Update checked references and remove naturally expired image records.

        Args:
            liveness: Checked image references mapped to their history presence.
            checked_at: Timestamp used when first marking an orphan.
            orphan_cutoff_exclusive: Orphans before this local-day boundary expire.
            retention_cutoff_exclusive: Images before this local-day boundary expire.

        Returns:
            Paths belonging to deleted records.
        """

        def reconcile_sync() -> list[Path]:
            with sqlite3.connect(self.database_path, timeout=10) as connection:
                connection.execute("BEGIN IMMEDIATE")
                for image_ref, is_live in liveness.items():
                    if is_live:
                        connection.execute(
                            """
                            UPDATE context_images SET orphaned_at = NULL
                            WHERE image_ref = ?
                            """,
                            (image_ref,),
                        )
                    else:
                        connection.execute(
                            """
                            UPDATE context_images
                            SET orphaned_at = COALESCE(orphaned_at, ?)
                            WHERE image_ref = ?
                            """,
                            (checked_at, image_ref),
                        )
                expired_rows: list[tuple[str, str]] = []
                expired_refs: set[str] = set()
                if retention_cutoff_exclusive is not None:
                    expired_rows.extend(
                        connection.execute(
                            """
                            SELECT image_ref, path FROM context_images
                            WHERE created_at < ?
                            """,
                            (retention_cutoff_exclusive,),
                        ).fetchall()
                    )
                    expired_refs.update(row[0] for row in expired_rows)
                for image_ref, is_live in liveness.items():
                    if is_live or image_ref in expired_refs:
                        continue
                    row = connection.execute(
                        """
                        SELECT image_ref, path FROM context_images
                        WHERE image_ref = ? AND orphaned_at IS NOT NULL
                          AND orphaned_at < ?
                        """,
                        (image_ref, orphan_cutoff_exclusive),
                    ).fetchone()
                    if row is None:
                        continue
                    expired_rows.append(row)
                    expired_refs.add(image_ref)
                connection.executemany(
                    "DELETE FROM context_images WHERE image_ref = ?",
                    [(image_ref,) for image_ref in expired_refs],
                )
                connection.commit()
                return [Path(row[1]) for row in expired_rows]

        return await asyncio.to_thread(reconcile_sync)

    async def cleanup(
        self, event_retention_days: int, audit_retention_days: int
    ) -> list[Path]:
        """Delete expired metadata and return owned temp files to remove.

        Args:
            event_retention_days: Event and request retention period.
            audit_retention_days: Audit retention period.

        Returns:
            Expired plugin-owned media paths.
        """

        now = int(time.time())
        event_cutoff = now - event_retention_days * 86400
        audit_cutoff = now - audit_retention_days * 86400

        def cleanup_sync() -> list[Path]:
            with sqlite3.connect(self.database_path, timeout=10) as connection:
                rows = connection.execute(
                    """
                    SELECT path FROM media_refs
                    WHERE expires_at < ? AND source IN ('download', 'base64')
                    """,
                    (now,),
                ).fetchall()
                connection.execute(
                    "DELETE FROM media_refs WHERE expires_at < ?", (now,)
                )
                connection.execute(
                    "DELETE FROM pending_actions WHERE expires_at < ?", (now - 86400,)
                )
                connection.execute(
                    "DELETE FROM events WHERE created_at < ?", (event_cutoff,)
                )
                connection.execute(
                    "DELETE FROM requests WHERE created_at < ?", (event_cutoff,)
                )
                connection.execute(
                    "DELETE FROM audit_logs WHERE created_at < ?", (audit_cutoff,)
                )
                return [Path(row[0]) for row in rows]

        return await asyncio.to_thread(cleanup_sync)
