"""Actual independent review, integration and freezing of one assessed revision."""
from .controller import submit_work
from .finalization import finalize_audit
from .stage1 import prepare_stage, stage_status


def prepare(db, *, audit_id, mode="independent", **kwargs):
    return prepare_stage(db, audit_id=audit_id, stage=2, mode=mode, **kwargs)


def record(db, *, envelope_bytes, response_bytes):
    return submit_work(db, envelope_bytes=envelope_bytes, response_bytes=response_bytes)


__all__ = ["prepare", "record", "stage_status", "finalize_audit"]
