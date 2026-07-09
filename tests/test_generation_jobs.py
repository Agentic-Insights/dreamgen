"""Tests for durable generation job persistence."""

from pathlib import Path

from src.services import GenerationJobCreate, GenerationProgressEvent, SQLiteGenerationJobStore


def test_generation_job_store_persists_state_transitions(tmp_path):
    store = SQLiteGenerationJobStore(tmp_path / "jobs.sqlite3")

    queued = store.create_job(
        GenerationJobCreate(
            prompt="durable job prompt",
            seed=17,
            client_request_id="req-job-1",
            metadata={"source": "test"},
        ),
        job_id="job-1",
    )

    assert queued["status"] == "queued"
    assert queued["request"]["prompt"] == "durable job prompt"
    assert queued["client_request_id"] == "req-job-1"

    running = store.start_job("job-1")
    assert running["status"] == "running"
    assert running["attempts"] == 1

    store.record_event(
        "job-1",
        GenerationProgressEvent(
            name="rendering",
            progress=50,
            label="Rendering",
            detail="Halfway there",
            payload={"phase": "image"},
        ),
    )
    completed = store.complete_job(
        "job-1",
        prompt="durable job prompt",
        image_path=Path("output/test.png"),
        relative_image_path="/images/test.png",
        backend="mock",
        model_name="mock-generator",
        generation_time=0.1,
        metadata={"backend": "mock", "seed": 17},
    )

    assert completed["status"] == "succeeded"
    assert completed["progress"] == 100
    assert completed["relative_image_path"] == "/images/test.png"
    assert completed["metadata"]["seed"] == 17

    reloaded = SQLiteGenerationJobStore(tmp_path / "jobs.sqlite3")
    job = reloaded.get_job("job-1", include_events=True)
    assert job is not None
    assert job["status"] == "succeeded"
    assert [event["name"] for event in job["events"]] == [
        "queued",
        "running",
        "rendering",
        "succeeded",
    ]


def test_generation_job_store_lists_and_records_failures(tmp_path):
    store = SQLiteGenerationJobStore(tmp_path / "jobs.sqlite3")
    store.create_job(GenerationJobCreate(prompt="will fail"), job_id="job-fail")
    store.start_job("job-fail")

    failed = store.fail_job("job-fail", "backend unavailable")

    assert failed["status"] == "failed"
    assert failed["error"] == "backend unavailable"
    assert store.list_jobs(status="failed")[0]["id"] == "job-fail"
    assert store.request_for_job("job-fail").prompt == "will fail"


def test_generation_job_store_marks_interrupted_jobs_failed(tmp_path):
    store = SQLiteGenerationJobStore(tmp_path / "jobs.sqlite3")
    store.create_job(GenerationJobCreate(prompt="queued"), job_id="queued-job")
    store.create_job(GenerationJobCreate(prompt="running"), job_id="running-job")
    store.create_job(GenerationJobCreate(prompt="done"), job_id="done-job")
    store.start_job("running-job")
    store.complete_job(
        "done-job",
        prompt="done",
        image_path=Path("output/done.png"),
        relative_image_path="/images/done.png",
        backend="mock",
        model_name="mock-generator",
        generation_time=0.1,
        metadata={"backend": "mock"},
    )

    reloaded = SQLiteGenerationJobStore(tmp_path / "jobs.sqlite3")
    recovered = reloaded.fail_interrupted_jobs("server restarted")

    assert {job["id"] for job in recovered} == {"queued-job", "running-job"}
    assert reloaded.get_job("queued-job")["status"] == "failed"
    assert reloaded.get_job("running-job")["status"] == "failed"
    assert reloaded.get_job("queued-job")["error"] == "server restarted"
    assert reloaded.get_job("done-job")["status"] == "succeeded"
    assert [event["name"] for event in reloaded.get_events("running-job")][-1] == "failed"
