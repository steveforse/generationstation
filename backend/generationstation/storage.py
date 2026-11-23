import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
    create_engine,
    delete,
    event,
    func,
    insert,
    select,
    update,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import insert as pg_insert

from .admission import evaluate_capacity

metadata = MetaData()
station = Table(
    "station", metadata,
    Column("id", Integer, primary_key=True),
    Column("instance_id", String(36), nullable=False),
    CheckConstraint("id = 1", name="station_singleton"),
)
models = Table(
    "models", metadata,
    Column("id", String(64), primary_key=True),
    Column("name", String(200), nullable=False),
    Column("workload", String(40), nullable=False),
)
profiles = Table(
    "model_profiles", metadata,
    Column("id", String(36), primary_key=True),
    Column("model_id", String(64), ForeignKey("models.id", ondelete="CASCADE"), nullable=False, unique=True),
    Column("name", String(200), nullable=False),
    Column("workload", String(40), nullable=False),
    Column("ram_peak_bytes", BigInteger, nullable=False),
    Column("gpu_vram_bytes_by_id", JSONB, nullable=False),
    Column("mode", String(20), nullable=False),
    Column("revision", Integer, nullable=False, server_default="1"),
    CheckConstraint("ram_peak_bytes > 0", name="profile_ram_positive"),
    CheckConstraint("mode = 'simulation'", name="profile_simulation_only"),
)
model_runtime = Table(
    "model_runtime", metadata,
    Column("model_id", String(64), ForeignKey("models.id", ondelete="CASCADE"), primary_key=True),
    Column("state", String(24), nullable=False, server_default="unloaded"),
    Column("active_operation_id", String(36)),
    Column("reservation_operation_id", String(36)),
    Column("active_worker_id", String(80)),
    Column("last_error_code", String(80)),
    Column("last_error_message", String(500)),
)
operations = Table(
    "operations", metadata,
    Column("id", String(36), primary_key=True),
    Column("model_id", String(64), ForeignKey("models.id", ondelete="CASCADE"), nullable=False),
    Column("profile_id", String(36), ForeignKey("model_profiles.id", ondelete="SET NULL")),
    Column("profile_revision", Integer),
    Column("action", String(12), nullable=False),
    Column("status", String(24), nullable=False),
    Column("idempotency_key", String(128), nullable=False, unique=True),
    Column("request_fingerprint", String(64), nullable=False),
    Column("parent_operation_id", String(36)),
    Column("reservation_operation_id", String(36)),
    Column("worker_id", String(80)),
    Column("refusal", JSONB),
    Column("launch", JSONB),
    Column("error_code", String(80)),
    Column("error_message", String(500)),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)
reservations = Table(
    "capacity_reservations", metadata,
    Column("operation_id", String(36), ForeignKey("operations.id", ondelete="CASCADE"), primary_key=True),
    Column("model_id", String(64), ForeignKey("models.id", ondelete="CASCADE"), nullable=False),
    Column("ram_bytes", BigInteger, nullable=False),
    Column("gpu_vram_bytes_by_id", JSONB, nullable=False),
    Column("active", Boolean, nullable=False, server_default="true"),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("released_at", DateTime(timezone=True)),
)

generation_jobs = Table(
    "generation_jobs", metadata,
    Column("id", String(36), primary_key=True),
    Column("model_id", String(64), ForeignKey("models.id", ondelete="CASCADE"), nullable=False),
    Column("load_operation_id", String(36)),
    Column("inputs", JSONB, nullable=False),
    Column("status", String(16), nullable=False),
    Column("progress", String(200)),
    Column("outputs", JSONB, nullable=False),
    Column("error_message", String(2000)),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    Column("finished_at", DateTime(timezone=True)),
    Column("details", JSONB),
    Column("launch", JSONB),
)

conversations = Table(
    "conversations", metadata,
    Column("id", String(36), primary_key=True),
    Column("title", String(200), nullable=False),
    Column("model_id", String(64), ForeignKey("models.id", ondelete="CASCADE"), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)
chat_messages = Table(
    "chat_messages", metadata,
    Column("id", String(36), primary_key=True),
    Column("conversation_id", String(36), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False),
    Column("position", Integer, nullable=False),
    Column("role", String(16), nullable=False),
    Column("content", Text, nullable=False, server_default=""),
    Column("reasoning", Text),
    Column("attachments", JSONB, nullable=False),
    Column("tool_calls", JSONB, nullable=False),
    Column("tool_call_id", String(80)),
    Column("job_id", String(36)),
    Column("status", String(16), nullable=False, server_default="done"),
    Column("error_message", String(2000)),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("note", String(500)),
    UniqueConstraint("conversation_id", "position", name="chat_messages_order"),
)

app_settings = Table(
    "app_settings", metadata,
    Column("key", String(80), primary_key=True),
    Column("value", JSONB),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)

SCHEDULER_LOCK_ID = 746238190
ADMISSION_LOCK_ID = 746238191


class Store:
    def __init__(self, database_url: str):
        self.engine = create_engine(
            database_url, pool_pre_ping=True, pool_size=2, max_overflow=2,
            pool_timeout=5, hide_parameters=True,
            connect_args={"connect_timeout": 5},
        )
        event.listen(self.engine, "connect", self._set_statement_timeout)
        self._scheduler_connection = None

    @staticmethod
    def _set_statement_timeout(connection, record):
        # Keep queries bounded without replacing caller-supplied libpq options
        # such as search_path or TLS settings. Autocommit makes SET persist as a
        # session setting rather than leaving an implicit transaction open.
        previous_autocommit = connection.autocommit
        try:
            connection.autocommit = True
            with connection.cursor() as cursor:
                cursor.execute("SET statement_timeout = 5000")
        finally:
            connection.autocommit = previous_autocommit

    def initialize(self) -> str:
        # Schema changes belong to Alembic, never implicit create_all at startup.
        with self.engine.begin() as conn:
            conn.execute(pg_insert(station).values(id=1, instance_id=str(uuid.uuid4())).on_conflict_do_nothing())
            return conn.execute(select(station.c.instance_id).where(station.c.id == 1)).scalar_one()

    def acquire_scheduler_lock(self):
        if self._scheduler_connection is not None:
            return
        connection = self.engine.connect()
        try:
            if not connection.execute(select(func.pg_try_advisory_lock(SCHEDULER_LOCK_ID))).scalar_one():
                raise RuntimeError("Another Generation Station scheduler already owns this database.")
            connection.commit()
            self._scheduler_connection = connection
        except Exception:
            connection.close()
            raise

    def release_scheduler_lock(self):
        if self._scheduler_connection is not None:
            try:
                self._scheduler_connection.execute(select(func.pg_advisory_unlock(SCHEDULER_LOCK_ID)))
                self._scheduler_connection.commit()
            finally:
                self._scheduler_connection.close()
                self._scheduler_connection = None

    @staticmethod
    def _now():
        return datetime.now(timezone.utc)

    def list_profiles(self) -> list[dict]:
        with self.engine.connect() as conn:
            return [dict(row) for row in conn.execute(select(profiles).order_by(profiles.c.name)).mappings()]

    def get_profile(self, model_id: str):
        with self.engine.connect() as conn:
            row = conn.execute(select(profiles).where(profiles.c.model_id == model_id)).mappings().first()
            return dict(row) if row else None

    def create_profile(self, values: dict):
        profile_id = str(uuid.uuid4())
        with self.engine.begin() as conn:
            existing_model = conn.execute(select(models).where(models.c.id == values["id"])
                                          .with_for_update()).mappings().first()
            if existing_model:
                # A deleted profile leaves catalog identity and operation history.
                # Allow the same identity to receive a new simulation profile.
                conn.execute(update(models).where(models.c.id == values["id"]).values(
                    name=values["name"], workload=values["workload"],
                ))
                conn.execute(pg_insert(model_runtime).values(
                    model_id=values["id"], state="unloaded",
                ).on_conflict_do_nothing(index_elements=[model_runtime.c.model_id]))
            else:
                conn.execute(insert(models).values(id=values["id"], name=values["name"], workload=values["workload"]))
                conn.execute(insert(model_runtime).values(model_id=values["id"], state="unloaded"))
            conn.execute(insert(profiles).values(
                id=profile_id, model_id=values["id"], name=values["name"], workload=values["workload"],
                ram_peak_bytes=values["ram_peak_bytes"], gpu_vram_bytes_by_id=values["gpu_vram_bytes_by_id"],
                mode="simulation", revision=1,
            ))
        return self.get_profile(values["id"])

    def update_profile(self, model_id: str, values: dict):
        with self.engine.begin() as conn:
            runtime = conn.execute(select(model_runtime).where(model_runtime.c.model_id == model_id)
                                   .with_for_update()).mappings().first()
            if not runtime:
                return None
            if runtime["state"] not in {"unloaded", "error"}:
                return {"busy": True}
            current = conn.execute(select(profiles).where(profiles.c.model_id == model_id)
                                   .with_for_update()).mappings().first()
            if not current:
                return None
            conn.execute(update(models).where(models.c.id == model_id).values(
                name=values["name"], workload=values["workload"],
            ))
            conn.execute(update(profiles).where(profiles.c.model_id == model_id).values(
                name=values["name"], workload=values["workload"],
                ram_peak_bytes=values["ram_peak_bytes"],
                gpu_vram_bytes_by_id=values["gpu_vram_bytes_by_id"],
                mode="simulation", revision=profiles.c.revision + 1,
            ))
        return self.get_profile(model_id)

    def delete_profile(self, model_id: str):
        with self.engine.begin() as conn:
            runtime = conn.execute(select(model_runtime).where(model_runtime.c.model_id == model_id)
                                   .with_for_update()).mappings().first()
            if not runtime:
                return "missing"
            if runtime["state"] not in {"unloaded", "error"}:
                return "busy"
            existing = conn.execute(select(profiles.c.id).where(profiles.c.model_id == model_id)).scalar_one_or_none()
            if existing is None:
                return "missing"
            conn.execute(delete(profiles).where(profiles.c.model_id == model_id))
        return "deleted"

    def list_models(self) -> list[dict]:
        with self.engine.connect() as conn:
            query = select(
                models.c.id, models.c.name, models.c.workload,
                model_runtime.c.state, profiles.c.id.label("profile_id"),
                profiles.c.revision.label("profile_revision"),
            ).select_from(models.join(model_runtime).outerjoin(profiles)).order_by(models.c.name)
            rows = conn.execute(query).mappings()
            result = []
            for row in rows:
                item = dict(row)
                item["loading_enabled"] = item["profile_id"] is not None and item["state"] in {"unloaded", "error"}
                item["profile"] = {"id": item.pop("profile_id"), "revision": item.pop("profile_revision")}
                result.append(item)
            return result

    def get_operation(self, operation_id: str):
        with self.engine.connect() as conn:
            row = conn.execute(select(operations).where(operations.c.id == operation_id)).mappings().first()
            return dict(row) if row else None

    def list_operations(self, limit=100):
        with self.engine.connect() as conn:
            rows = conn.execute(select(operations).order_by(operations.c.created_at.desc()).limit(limit)).mappings()
            return [dict(row) for row in rows]

    def find_idempotent_operation(self, idempotency_key: str):
        with self.engine.connect() as conn:
            row = conn.execute(select(operations).where(
                operations.c.idempotency_key == idempotency_key,
            )).mappings().first()
            return dict(row) if row else None

    def active_reservations(self, conn=None) -> list[dict]:
        if conn is None:
            with self.engine.connect() as connection:
                return self.active_reservations(connection)
        rows = conn.execute(select(reservations).where(reservations.c.active.is_(True))).mappings()
        return [dict(row) for row in rows]

    def create_load_operation(self, *, model_id, profile_id, idempotency_key, fingerprint, host,
                              ram_headroom_bytes, gpu_headroom_bytes):
        now, operation_id = self._now(), str(uuid.uuid4())
        with self.engine.begin() as conn:
            # Serialize the complete capacity snapshot + active-reservation read
            # + reservation insert, including loads for different models.
            conn.execute(select(func.pg_advisory_xact_lock(ADMISSION_LOCK_ID)))
            existing = conn.execute(select(operations).where(
                operations.c.idempotency_key == idempotency_key,
            )).mappings().first()
            if existing:
                if existing["request_fingerprint"] != fingerprint:
                    return {"idempotency_conflict": True, "operation": dict(existing)}
                return {"existing": True, "operation": dict(existing)}
            model = conn.execute(select(models).where(models.c.id == model_id)).mappings().first()
            runtime = conn.execute(select(model_runtime).where(
                model_runtime.c.model_id == model_id,
            ).with_for_update()).mappings().first()
            profile = conn.execute(select(profiles).where(
                profiles.c.id == profile_id, profiles.c.model_id == model_id,
            ).with_for_update()).mappings().first()
            if not model or not profile or not runtime:
                refusal = {"code": "PROFILE_NOT_FOUND", "message": "The model or simulation profile was not found.",
                           "resources": []}
                return self._insert_refusal(conn, operation_id, model_id,
                                            profile_id if profile else None, idempotency_key,
                                            fingerprint, refusal, now)
            if runtime["state"] not in {"unloaded", "error"}:
                refusal = {"code": "MODEL_BUSY", "message": "This model already has an active worker operation.",
                           "resources": []}
                return self._insert_refusal(conn, operation_id, model_id, profile_id, idempotency_key,
                                            fingerprint, refusal, now, profile["revision"])
            failure = evaluate_capacity(host, dict(profile), self.active_reservations(conn),
                                        ram_headroom_bytes, gpu_headroom_bytes)
            if failure:
                return self._insert_refusal(conn, operation_id, model_id, profile_id, idempotency_key,
                                            fingerprint, failure, now, profile["revision"])
            operation = {
                "id": operation_id, "model_id": model_id, "profile_id": profile_id,
                "profile_revision": profile["revision"], "action": "load", "status": "loading",
                "idempotency_key": idempotency_key, "request_fingerprint": fingerprint,
                "parent_operation_id": None, "reservation_operation_id": operation_id,
                "worker_id": None, "refusal": None,
                "error_code": None, "error_message": None, "created_at": now, "updated_at": now,
            }
            conn.execute(insert(operations).values(**operation))
            conn.execute(insert(reservations).values(
                operation_id=operation_id, model_id=model_id,
                ram_bytes=profile["ram_peak_bytes"], gpu_vram_bytes_by_id=profile["gpu_vram_bytes_by_id"],
                active=True, created_at=now, released_at=None,
            ))
            conn.execute(update(model_runtime).where(model_runtime.c.model_id == model_id).values(
                state="loading", active_operation_id=operation_id,
                reservation_operation_id=operation_id, active_worker_id=None,
                last_error_code=None, last_error_message=None,
            ))
            return {"operation": operation, "existing": False}

    def sync_runtime_models(self, entries):
        """Make each configured runtime a catalog model. Never deletes history for removed ones."""
        with self.engine.begin() as conn:
            for entry in entries:
                conn.execute(pg_insert(models).values(
                    id=entry["id"], name=entry["name"], workload=entry["workload"],
                ).on_conflict_do_update(index_elements=[models.c.id],
                                        set_={"name": entry["name"], "workload": entry["workload"]}))
                conn.execute(pg_insert(model_runtime).values(
                    model_id=entry["id"], state="unloaded",
                ).on_conflict_do_nothing(index_elements=[model_runtime.c.model_id]))

    def latest_launches(self):
        """The launch settings of each model's most recent real load, for UI defaults."""
        with self.engine.connect() as conn:
            rows = conn.execute(
                select(operations.c.model_id, operations.c.launch, operations.c.status)
                .where(operations.c.action == "load", operations.c.launch.is_not(None))
                .distinct(operations.c.model_id)
                .order_by(operations.c.model_id, operations.c.created_at.desc())
            ).mappings()
            return {row["model_id"]: {"launch": row["launch"], "status": row["status"]} for row in rows}

    def runtime_states(self):
        with self.engine.connect() as conn:
            rows = conn.execute(select(model_runtime)).mappings()
            return {row["model_id"]: dict(row) for row in rows}

    def active_runtime_operations(self):
        """Real-runtime operations that may still own a process."""
        with self.engine.connect() as conn:
            rows = conn.execute(select(operations).where(
                operations.c.launch.is_not(None),
                operations.c.status.in_(["loading", "ready", "unloading", "cleanup_failed"]),
            )).mappings()
            return [dict(row) for row in rows]

    def create_runtime_load_operation(self, *, model_id, launch, requirement, idempotency_key, fingerprint,
                                      host, ram_headroom_bytes, gpu_headroom_bytes):
        now, operation_id = self._now(), str(uuid.uuid4())
        with self.engine.begin() as conn:
            conn.execute(select(func.pg_advisory_xact_lock(ADMISSION_LOCK_ID)))
            existing = conn.execute(select(operations).where(
                operations.c.idempotency_key == idempotency_key,
            )).mappings().first()
            if existing:
                if existing["request_fingerprint"] != fingerprint:
                    return {"idempotency_conflict": True, "operation": dict(existing)}
                return {"existing": True, "operation": dict(existing)}
            runtime = conn.execute(select(model_runtime).where(
                model_runtime.c.model_id == model_id,
            ).with_for_update()).mappings().first()
            if not runtime:
                return {"missing_model": True, "operation": None}
            base = {"id": operation_id, "model_id": model_id, "profile_id": None, "profile_revision": None,
                    "action": "load", "idempotency_key": idempotency_key, "request_fingerprint": fingerprint,
                    "parent_operation_id": None, "worker_id": None, "launch": launch,
                    "error_code": None, "error_message": None, "created_at": now, "updated_at": now}
            if runtime["state"] not in {"unloaded", "error"}:
                refusal = {"code": "MODEL_BUSY", "message": "This model already has an active worker operation.",
                           "resources": []}
                operation = {**base, "status": "refused", "reservation_operation_id": None, "refusal": refusal}
                conn.execute(insert(operations).values(**operation))
                return {"operation": operation, "existing": False}
            pseudo_profile = {"mode": "estimate", "ram_peak_bytes": requirement["ram_bytes"],
                              "gpu_vram_bytes_by_id": requirement["gpu_vram_bytes_by_id"]}
            failure = evaluate_capacity(host, pseudo_profile, self.active_reservations(conn),
                                        ram_headroom_bytes, gpu_headroom_bytes)
            if failure:
                operation = {**base, "status": "refused", "reservation_operation_id": None, "refusal": failure}
                conn.execute(insert(operations).values(**operation))
                return {"operation": operation, "existing": False}
            operation = {**base, "status": "loading", "reservation_operation_id": operation_id, "refusal": None}
            conn.execute(insert(operations).values(**operation))
            conn.execute(insert(reservations).values(
                operation_id=operation_id, model_id=model_id, ram_bytes=requirement["ram_bytes"],
                gpu_vram_bytes_by_id=requirement["gpu_vram_bytes_by_id"], active=True,
                created_at=now, released_at=None,
            ))
            conn.execute(update(model_runtime).where(model_runtime.c.model_id == model_id).values(
                state="loading", active_operation_id=operation_id, reservation_operation_id=operation_id,
                active_worker_id=None, last_error_code=None, last_error_message=None,
            ))
            return {"operation": operation, "existing": False}

    def _insert_refusal(self, conn, operation_id, model_id, profile_id, key, fingerprint,
                        refusal, now, profile_revision=None):
        operation = {
            "id": operation_id, "model_id": model_id, "profile_id": profile_id,
            "profile_revision": profile_revision, "action": "load", "status": "refused",
            "idempotency_key": key, "request_fingerprint": fingerprint,
            "parent_operation_id": None, "reservation_operation_id": None,
            "worker_id": None, "refusal": refusal,
            "error_code": None, "error_message": None, "created_at": now, "updated_at": now,
        }
        # For a missing model, omit the operation because its FK cannot be satisfied.
        if conn.execute(select(models.c.id).where(models.c.id == model_id)).scalar_one_or_none() is None:
            return {"operation": operation, "missing_model": True}
        conn.execute(insert(operations).values(**operation))
        return {"operation": operation, "existing": False}

    def begin_unload(self, *, model_id, idempotency_key, fingerprint):
        now, operation_id = self._now(), str(uuid.uuid4())
        with self.engine.begin() as conn:
            conn.execute(select(func.pg_advisory_xact_lock(ADMISSION_LOCK_ID)))
            existing = conn.execute(select(operations).where(
                operations.c.idempotency_key == idempotency_key,
            )).mappings().first()
            if existing:
                if existing["request_fingerprint"] != fingerprint:
                    return {"idempotency_conflict": True, "operation": dict(existing)}
                return {"existing": True, "operation": dict(existing)}
            runtime = conn.execute(select(model_runtime).where(
                model_runtime.c.model_id == model_id,
            ).with_for_update()).mappings().first()
            if not runtime:
                return {"missing_model": True}
            if runtime["state"] not in {"simulation_ready", "ready", "cleanup_failed"}:
                return {"busy": True, "state": runtime["state"]}
            parent_id = runtime["active_operation_id"]
            parent = conn.execute(select(operations).where(operations.c.id == parent_id)).mappings().first()
            launch = parent["launch"] if parent else None
            operation = {
                "id": operation_id, "model_id": model_id,
                "profile_id": parent["profile_id"] if parent else None,
                "profile_revision": parent["profile_revision"] if parent else None,
                "action": "unload", "status": "unloading", "idempotency_key": idempotency_key,
                "request_fingerprint": fingerprint, "parent_operation_id": parent_id,
                "reservation_operation_id": runtime["reservation_operation_id"],
                "worker_id": runtime["active_worker_id"], "refusal": None, "launch": launch,
                "error_code": None, "error_message": None, "created_at": now, "updated_at": now,
            }
            conn.execute(insert(operations).values(**operation))
            conn.execute(update(model_runtime).where(model_runtime.c.model_id == model_id).values(
                state="unloading", active_operation_id=operation_id,
            ))
            return {"operation": operation, "existing": False}

    def update_operation(self, operation_id, *, status, worker_id=None, error_code=None,
                         error_message=None, refusal=None):
        now = self._now()
        with self.engine.begin() as conn:
            op = conn.execute(select(operations).where(operations.c.id == operation_id)
                              .with_for_update()).mappings().first()
            if not op:
                return None
            values = {"status": status, "updated_at": now}
            if worker_id is not None:
                values["worker_id"] = worker_id
            if error_code is not None:
                values["error_code"] = error_code
            if error_message is not None:
                values["error_message"] = error_message[:500]
            if refusal is not None:
                values["refusal"] = refusal
            conn.execute(update(operations).where(operations.c.id == operation_id).values(**values))
            state = {"simulation_ready": "simulation_ready", "ready": "ready", "unloading": "unloading",
                     "unloaded": "unloaded", "failed": "error", "cleanup_failed": "cleanup_failed"}.get(status)
            if status == "loading" and worker_id is not None:
                conn.execute(update(model_runtime).where(model_runtime.c.model_id == op["model_id"])
                             .values(active_worker_id=worker_id))
            if status == "ready":
                # A real process's memory now shows in telemetry; keeping the reservation
                # would count the same memory twice for the next admission.
                conn.execute(update(reservations).where(
                    reservations.c.operation_id == operation_id, reservations.c.active.is_(True),
                ).values(active=False, released_at=now))
            if state:
                runtime_values = {"state": state}
                if status in {"unloaded", "failed"}:
                    runtime_values.update(active_operation_id=None, reservation_operation_id=None,
                                          active_worker_id=None)
                    runtime_values["last_error_code"] = error_code if status == "failed" else None
                    runtime_values["last_error_message"] = error_message[:500] if status == "failed" and error_message else None
                elif status in {"simulation_ready", "ready", "cleanup_failed"}:
                    runtime_values["active_operation_id"] = operation_id
                    if worker_id is not None:
                        runtime_values["active_worker_id"] = worker_id
                    if status == "cleanup_failed":
                        runtime_values.update(last_error_code=error_code, last_error_message=error_message[:500] if error_message else None)
                conn.execute(update(model_runtime).where(model_runtime.c.model_id == op["model_id"])
                             .values(**runtime_values))
            if status in {"unloaded", "failed"}:
                target = op["reservation_operation_id"] or (operation_id if op["action"] == "load" else None)
                if target:
                    conn.execute(update(reservations).where(
                        reservations.c.operation_id == target, reservations.c.active.is_(True),
                    ).values(active=False, released_at=now))
        return self.get_operation(operation_id)

    def reconcile_restart(self, keep_operation_ids=()):
        """Fail operations whose worker did not survive a restart; keep re-adopted real processes."""
        now = self._now()
        keep = set(keep_operation_ids)
        with self.engine.begin() as conn:
            active_ops = conn.execute(select(operations).where(
                operations.c.status.in_(["loading", "simulation_ready", "ready", "unloading", "cleanup_failed"]),
            )).mappings().all()
            # A start stays "ready" after its model is stopped (the stop is its own operation), so only
            # each model's most recent operation, ignoring refusals, can describe what is running now.
            latest = dict(conn.execute(
                select(operations.c.model_id, func.max(operations.c.created_at))
                .where(operations.c.status != "refused").group_by(operations.c.model_id)
            ).all())
            for op in active_ops:
                if op["id"] in keep:
                    # Re-adopted: make the model's record point at it again.
                    conn.execute(update(model_runtime).where(model_runtime.c.model_id == op["model_id"]).values(
                        state=op["status"], active_operation_id=op["id"], active_worker_id=op["worker_id"],
                        last_error_code=None, last_error_message=None,
                    ))
                    continue
                if op["created_at"] < latest.get(op["model_id"], op["created_at"]):
                    continue  # superseded by a later stop or start; it says nothing about the model now
                real = op["launch"] is not None
                message = ("The runtime process was not running after the service restarted." if real else
                           "The fake worker is process-local and was discarded during service restart.")
                conn.execute(update(operations).where(operations.c.id == op["id"]).values(
                    status="failed", error_code="SERVICE_RESTART", error_message=message, updated_at=now,
                ))
                conn.execute(update(model_runtime).where(model_runtime.c.model_id == op["model_id"]).values(
                    state="error", active_operation_id=None, reservation_operation_id=None,
                    active_worker_id=None,
                    last_error_code="SERVICE_RESTART",
                    last_error_message=("The runtime process was gone after the service restarted." if real else
                                        "The fake worker was discarded during service restart."),
                ))
                conn.execute(update(reservations).where(
                    reservations.c.operation_id == (op["reservation_operation_id"]
                                                     or (op["id"] if op["action"] == "load" else None)),
                ).values(active=False, released_at=now))

    # ----- generation jobs ---------------------------------------------------------------

    def create_job(self, *, job_id, model_id, load_operation_id, inputs, launch=None):
        now = self._now()
        row = {"id": job_id, "model_id": model_id, "load_operation_id": load_operation_id, "inputs": inputs,
               "status": "queued", "progress": None, "outputs": [], "error_message": None,
               "created_at": now, "updated_at": now, "finished_at": None, "details": None, "launch": launch}
        with self.engine.begin() as conn:
            conn.execute(insert(generation_jobs).values(**row))
        return row

    def update_job(self, job_id, *, status, progress=None, outputs=None, error_message=None, details=None):
        now = self._now()
        values = {"status": status, "progress": progress, "updated_at": now}
        if outputs is not None:
            values["outputs"] = outputs
        if details is not None:
            values["details"] = details
        if error_message is not None:
            values["error_message"] = error_message[:2000]
        if status in {"done", "failed", "cancelled"}:
            values["finished_at"] = now
        with self.engine.begin() as conn:
            conn.execute(update(generation_jobs).where(generation_jobs.c.id == job_id).values(**values))
        return self.get_job(job_id)

    def get_job(self, job_id):
        with self.engine.connect() as conn:
            row = conn.execute(select(generation_jobs).where(generation_jobs.c.id == job_id)).mappings().first()
            return dict(row) if row else None

    def delete_job(self, job_id):
        with self.engine.begin() as conn:
            return conn.execute(delete(generation_jobs).where(generation_jobs.c.id == job_id)).rowcount > 0

    def list_jobs(self, model_id=None, limit=50):
        query = select(generation_jobs).order_by(generation_jobs.c.created_at.desc()).limit(limit)
        if model_id:
            query = query.where(generation_jobs.c.model_id == model_id)
        with self.engine.connect() as conn:
            return [dict(row) for row in conn.execute(query).mappings()]

    def find_jobs_by_prefix(self, prefix, limit=2):
        """Jobs whose ID starts with `prefix` (a short reference to a result, as the chat model writes it)."""
        query = (select(generation_jobs).where(generation_jobs.c.id.like(prefix.replace("%", "") + "%"))
                 .order_by(generation_jobs.c.created_at.desc()).limit(limit))
        with self.engine.connect() as conn:
            return [dict(row) for row in conn.execute(query).mappings()]

    # ----- chat ------------------------------------------------------------------------------

    def list_conversations(self, limit=200):
        query = select(conversations).order_by(conversations.c.updated_at.desc()).limit(limit)
        with self.engine.connect() as conn:
            return [dict(row) for row in conn.execute(query).mappings()]

    def create_conversation(self, *, conversation_id, title, model_id):
        now = self._now()
        row = {"id": conversation_id, "title": title, "model_id": model_id, "created_at": now, "updated_at": now}
        with self.engine.begin() as conn:
            conn.execute(insert(conversations).values(**row))
        return row

    def get_conversation(self, conversation_id):
        with self.engine.connect() as conn:
            row = conn.execute(select(conversations).where(conversations.c.id == conversation_id)).mappings().first()
            return dict(row) if row else None

    def update_conversation(self, conversation_id, **values):
        values["updated_at"] = self._now()
        with self.engine.begin() as conn:
            conn.execute(update(conversations).where(conversations.c.id == conversation_id).values(**values))
        return self.get_conversation(conversation_id)

    def delete_conversation(self, conversation_id):
        with self.engine.begin() as conn:
            return conn.execute(delete(conversations).where(conversations.c.id == conversation_id)).rowcount > 0

    def list_messages(self, conversation_id):
        query = (select(chat_messages).where(chat_messages.c.conversation_id == conversation_id)
                 .order_by(chat_messages.c.position))
        with self.engine.connect() as conn:
            return [dict(row) for row in conn.execute(query).mappings()]

    def add_message(self, conversation_id, *, role, content="", reasoning=None, attachments=None, tool_calls=None,
                    tool_call_id=None, job_id=None, status="done", error_message=None, note=None):
        now = self._now()
        row = {"id": str(uuid.uuid4()), "conversation_id": conversation_id, "role": role, "content": content,
               "note": note[:500] if note else None,
               "reasoning": reasoning or None, "attachments": attachments or [], "tool_calls": tool_calls or [],
               "tool_call_id": tool_call_id, "job_id": job_id, "status": status,
               "error_message": error_message[:2000] if error_message else None, "created_at": now}
        with self.engine.begin() as conn:
            last = conn.execute(select(func.max(chat_messages.c.position))
                                .where(chat_messages.c.conversation_id == conversation_id)).scalar()
            row["position"] = (last or 0) + 1
            conn.execute(insert(chat_messages).values(**row))
            conn.execute(update(conversations).where(conversations.c.id == conversation_id).values(updated_at=now))
        return row

    # ----- settings ----------------------------------------------------------------------------

    def get_setting(self, key, default=None):
        with self.engine.connect() as conn:
            row = conn.execute(select(app_settings.c.value).where(app_settings.c.key == key)).first()
        return default if row is None else row[0]

    def set_setting(self, key, value):
        statement = pg_insert(app_settings).values(key=key, value=value, updated_at=self._now())
        with self.engine.begin() as conn:
            conn.execute(statement.on_conflict_do_update(index_elements=["key"],
                                                         set_={"value": value, "updated_at": self._now()}))

    def close(self):
        try:
            self.release_scheduler_lock()
        finally:
            self.engine.dispose()
