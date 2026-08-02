from src.utils.observability import read_lifecycle_events, write_lifecycle_event


def test_lifecycle_events_are_written_and_read_in_reverse_chronological_order(tmp_path):
    metrics_dir = tmp_path / "metrics"
    write_lifecycle_event(metrics_dir, {"name": "generation_started", "id": "one"})
    write_lifecycle_event(metrics_dir, {"name": "generation_completed", "id": "one"})

    events = read_lifecycle_events(metrics_dir)
    assert [event["name"] for event in events] == [
        "generation_completed",
        "generation_started",
    ]
