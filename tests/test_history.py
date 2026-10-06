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


def test_each_run_gets_a_log_named_by_its_run_id(tmp_path):
    h = History(directory=str(tmp_path), log_dir="logs")
    h.log("site 101 started\n")
    h.log("site 101 done\n")
    h.finish(FakeReport())
    h.close()
    assert h.log_path == "logs/%s.log" % h.run_id
    text = (tmp_path / h.log_path).read_text()
    assert "site 101 started" in text and "site 101 done" in text
    # the run record points at it, relative to the checkout, so the dashboard can link it
    assert read(tmp_path / "runs.jsonl")[0]["log"] == h.log_path


def test_lines_logged_after_finish_still_land_in_the_file(tmp_path):
    # main() logs the summary after finish(); it must not be lost
    h = History(directory=str(tmp_path), log_dir="logs")
    h.finish(FakeReport())
    h.log("summary\n")
    h.close()
    assert "summary" in (tmp_path / h.log_path).read_text()


def test_without_a_log_dir_nothing_is_written_and_the_record_says_so(tmp_path):
    h = History(directory=str(tmp_path))
    h.log("ignored\n")
    h.finish(FakeReport())
    assert h.log_path is None
    assert read(tmp_path / "runs.jsonl")[0]["log"] is None
    assert not (tmp_path / "logs").exists()


def test_old_logs_are_pruned_to_the_newest_few(tmp_path):
    import os, time as _t
    d = tmp_path / "logs"
    d.mkdir()
    for i in range(5):
        f = d / ("old%d.log" % i)
        f.write_text("x")
        os.utime(f, (_t.time() - 1000 + i, _t.time() - 1000 + i))
    h = History(directory=str(tmp_path), log_dir="logs", log_keep=3)
    h.close()
    left = sorted(p.name for p in d.iterdir())
    # the new run's own log plus the two newest old ones survive
    assert len(left) == 3
    assert h.run_id + ".log" in left
    assert "old0.log" not in left and "old4.log" in left
