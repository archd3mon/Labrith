"""
Tests for lib/trace.py — append-only JSONL trace writer and read helpers.

Covers:
- Writes produce valid JSONL with correct fields.
- Sequence numbers are monotonically increasing.
- Multiple writes append (do not overwrite).
- read_trace parses all entries correctly.
- filter_trace narrows by agent, event_type, run_id.
- No modify/delete API exists (design constraint).
- TraceWriter is safe to write concurrently from threads.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from lib.trace import TraceWriter, TraceEntry, read_trace, filter_trace


# ===========================================================================
# Basic write + read
# ===========================================================================
class TestTraceWriteRead:
    def test_write_creates_file(self, tmp_path):
        trace_file = tmp_path / "trace.jsonl"
        tw = TraceWriter(trace_file, run_id="run-001")
        tw.write(agent="planner", event_type="routing", payload={"next": "designer"})
        assert trace_file.exists()

    def test_write_produces_valid_jsonl(self, tmp_path):
        trace_file = tmp_path / "trace.jsonl"
        tw = TraceWriter(trace_file, run_id="run-001")
        tw.write(agent="planner", event_type="message", payload={"text": "hello"})
        line = trace_file.read_text(encoding="utf-8").strip()
        data = json.loads(line)
        assert data["run_id"] == "run-001"
        assert data["seq"] == 0
        assert data["agent"] == "planner"
        assert data["event_type"] == "message"
        assert "timestamp" in data

    def test_read_trace_returns_entries(self, tmp_path):
        trace_file = tmp_path / "trace.jsonl"
        tw = TraceWriter(trace_file, run_id="run-002")
        tw.write(agent="engineer", event_type="proof")
        tw.write(agent="qa", event_type="proof")
        entries = read_trace(trace_file)
        assert len(entries) == 2
        assert all(isinstance(e, TraceEntry) for e in entries)

    def test_read_empty_file(self, tmp_path):
        trace_file = tmp_path / "empty.jsonl"
        trace_file.write_text("", encoding="utf-8")
        entries = read_trace(trace_file)
        assert entries == []

    def test_read_nonexistent_file(self, tmp_path):
        entries = read_trace(tmp_path / "nope.jsonl")
        assert entries == []


# ===========================================================================
# Sequence numbering and append-only behaviour
# ===========================================================================
class TestTraceSequence:
    def test_sequence_is_monotonic(self, tmp_path):
        trace_file = tmp_path / "trace.jsonl"
        tw = TraceWriter(trace_file, run_id="run-003")
        for i in range(5):
            entry = tw.write(agent="planner", event_type="step")
            assert entry.seq == i
        entries = read_trace(trace_file)
        seqs = [e.seq for e in entries]
        assert seqs == [0, 1, 2, 3, 4]

    def test_append_does_not_overwrite(self, tmp_path):
        trace_file = tmp_path / "trace.jsonl"
        tw = TraceWriter(trace_file, run_id="run-004")
        tw.write(agent="planner", event_type="start")
        first_line = trace_file.read_text(encoding="utf-8")

        tw.write(agent="designer", event_type="output")
        all_text = trace_file.read_text(encoding="utf-8")

        # First line must still be there, unchanged.
        assert all_text.startswith(first_line.rstrip("\n"))
        lines = [l for l in all_text.strip().split("\n") if l]
        assert len(lines) == 2

    def test_second_writer_appends(self, tmp_path):
        """Opening a second TraceWriter on the same file appends."""
        trace_file = tmp_path / "trace.jsonl"
        tw1 = TraceWriter(trace_file, run_id="run-005")
        tw1.write(agent="planner", event_type="start")

        tw2 = TraceWriter(trace_file, run_id="run-005")
        tw2.write(agent="engineer", event_type="build")

        entries = read_trace(trace_file)
        assert len(entries) == 2


# ===========================================================================
# Filtering
# ===========================================================================
class TestTraceFilter:
    def _write_sample(self, tmp_path) -> list[TraceEntry]:
        trace_file = tmp_path / "trace.jsonl"
        tw = TraceWriter(trace_file, run_id="run-006")
        tw.write(agent="planner", event_type="routing", payload={"next": "designer"})
        tw.write(agent="designer", event_type="proof", payload={"spec": "v1"})
        tw.write(agent="engineer", event_type="proof", payload={"build": "ok"})
        tw.write(agent="planner", event_type="routing", payload={"next": "qa"})
        return read_trace(trace_file)

    def test_filter_by_agent(self, tmp_path):
        entries = self._write_sample(tmp_path)
        result = filter_trace(entries, agent="planner")
        assert len(result) == 2
        assert all(e.agent == "planner" for e in result)

    def test_filter_by_event_type(self, tmp_path):
        entries = self._write_sample(tmp_path)
        result = filter_trace(entries, event_type="proof")
        assert len(result) == 2

    def test_filter_by_run_id(self, tmp_path):
        entries = self._write_sample(tmp_path)
        result = filter_trace(entries, run_id="run-006")
        assert len(result) == 4
        result_miss = filter_trace(entries, run_id="run-999")
        assert len(result_miss) == 0

    def test_combined_filter(self, tmp_path):
        entries = self._write_sample(tmp_path)
        result = filter_trace(entries, agent="planner", event_type="routing")
        assert len(result) == 2


# ===========================================================================
# No modify/delete API (design constraint check)
# ===========================================================================
class TestTraceImmutability:
    def test_no_delete_method(self):
        assert not hasattr(TraceWriter, "delete")

    def test_no_truncate_method(self):
        assert not hasattr(TraceWriter, "truncate")

    def test_no_overwrite_method(self):
        assert not hasattr(TraceWriter, "overwrite")

    def test_no_edit_method(self):
        assert not hasattr(TraceWriter, "edit")


# ===========================================================================
# Thread safety
# ===========================================================================
class TestTraceThreadSafety:
    def test_concurrent_writes(self, tmp_path):
        trace_file = tmp_path / "trace.jsonl"
        tw = TraceWriter(trace_file, run_id="run-007")
        n_threads = 10
        writes_per_thread = 20

        def writer():
            for _ in range(writes_per_thread):
                tw.write(agent="planner", event_type="step")

        threads = [threading.Thread(target=writer) for _ in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        entries = read_trace(trace_file)
        assert len(entries) == n_threads * writes_per_thread
        # All sequence numbers should be unique
        seqs = [e.seq for e in entries]
        assert len(set(seqs)) == len(seqs)
