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
