import json

from scraper.history import ERROR, OK, SKIPPED, STALE, History


class FakeReport:
    cutoff = "2026-09-09"
    sites = 3
    ran = 2
    skipped = 1
    errors = 1
    found = 10
    parsed = 8
    stored = 5
    dupes = 3
    ledeless = 1
    empty = [202]
    problems = [(202, "found=4 parsed=0")]


def read(path):
    return [json.loads(l) for l in open(path, encoding="utf-8")]


def test_a_site_line_is_written_per_call(tmp_path):
    h = History(directory=str(tmp_path))
    h.site(101, OK, found=6, parsed=5, stored=3, dupes=2)
    h.site(202, STALE, found=4, parsed=0, problems=["found=4 parsed=0"])
    h.site(303, SKIPPED, error="no recipe")
    rows = read(tmp_path / "run_sites.jsonl")
    assert [r["a_id"] for r in rows] == [101, 202, 303]
    assert [r["state"] for r in rows] == [OK, STALE, SKIPPED]
    assert rows[0]["stored"] == 3
    assert rows[1]["problems"] == ["found=4 parsed=0"]
    assert rows[2]["error"] == "no recipe"
    # every line carries the same run_id, which is what joins them to the run
    assert len({r["run_id"] for r in rows}) == 1


def test_finish_writes_one_run_summary(tmp_path):
    h = History(directory=str(tmp_path))
    h.finish(FakeReport(), days=3, workers=2)
    runs = read(tmp_path / "runs.jsonl")
    assert len(runs) == 1
    run = runs[0]
    assert run["stored"] == 5 and run["dupes"] == 3 and run["ran"] == 2
    assert run["days"] == 3 and run["workers"] == 2
    assert run["empty"] == [202]
    assert run["problems"] == [[202, "found=4 parsed=0"]]
    assert run["run_id"] == h.run_id
    assert run["seconds"] >= 0


def test_runs_append_rather_than_overwrite(tmp_path):
    History(directory=str(tmp_path)).finish(FakeReport())
    History(directory=str(tmp_path)).finish(FakeReport())
    assert len(read(tmp_path / "runs.jsonl")) == 2


def test_a_write_that_fails_cannot_kill_the_run(tmp_path):
    # the directory does not exist, so every open() raises
    h = History(directory=str(tmp_path / "nope"))
    h.site(101, ERROR, error="boom")
    h.finish(FakeReport())
    assert h.write_errors == 2  # counted, not raised
