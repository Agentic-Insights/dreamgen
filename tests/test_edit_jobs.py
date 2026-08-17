from src.services.edit_jobs import SQLiteEditJobStore


def test_edit_job_store_persists_lineage_and_lifecycle(tmp_path):
    store = SQLiteEditJobStore(tmp_path / "edit-jobs.sqlite3")

    created = store.create_job(
        prompt="make the sky warmer",
        strength=0.65,
        backend="mock",
        source_path="/images/source.png",
        source_filename="source.png",
        metadata={"operation": "edit"},
    )
    assert created["status"] == "queued"
    assert created["root_job_id"] == created["id"]
    assert created["version"] == 1
    assert created["decision_state"] == "pending"

    store.start_job(created["id"])
    store.complete_job(
        created["id"],
        original_path="/images/original.png",
        edited_path="/images/edited.png",
        metadata={"edit_job_id": created["id"], "role": "result"},
    )

    result = store.get_job(created["id"])
    assert result is not None
    assert result["status"] == "succeeded"
    assert result["original_path"] == "/images/original.png"
    assert result["edited_path"] == "/images/edited.png"
    assert result["metadata"]["edit_job_id"] == created["id"]

    approved = store.set_decision(created["id"], "approved", manifest_path="manifest.json")
    assert approved["decision_state"] == "approved"
    assert approved["manifest_path"] == "manifest.json"


def test_edit_job_store_preserves_branch_history_and_cancellation(tmp_path):
    store = SQLiteEditJobStore(tmp_path / "edit-jobs.sqlite3")
    root = store.create_job(prompt="root", strength=0, backend="mage-flow-edit")
    child = store.create_job(
        prompt="branch",
        strength=0,
        backend="mage-flow-edit",
        root_job_id=root["id"],
        parent_job_id=root["id"],
        version=2,
    )
    cancelled = store.cancel_job(child["id"])

    assert cancelled["status"] == "cancelled"
    assert child["parent_job_id"] == root["id"]
    assert [job["version"] for job in store.list_jobs(root["id"])] == [1, 2]
