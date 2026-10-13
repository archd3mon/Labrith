"""
Tests for lib/proofs.py — create_proof and validate_proof.

Covers:
- Accept valid proofs with existing evidence files.
- Reject missing fields (each required field).
- Reject invalid agent names.
- Reject empty evidence list.
- Reject evidence refs that don't exist on disk.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from lib.proofs import create_proof, validate_proof
from lib.models import ProofOfWork


# ---- Helpers ---------------------------------------------------------------
def _make_evidence_files(base: Path, refs: list[str]) -> list[dict[str, str]]:
    """Create files on disk and return evidence dicts."""
    evidence = []
    for ref in refs:
        p = base / ref
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("evidence content", encoding="utf-8")
        evidence.append({"type": "log", "ref": ref})
    return evidence


# ===========================================================================
# create_proof
# ===========================================================================
class TestCreateProof:
    def test_creates_valid_proof(self, tmp_path):
        evidence = _make_evidence_files(tmp_path, ["artifacts/build.log"])
        proof = create_proof(
            agent="engineer",
            task_id="T-01",
            claim="Build passes",
            evidence=evidence,
            reasoning="Ran npm build successfully.",
        )
        assert isinstance(proof, ProofOfWork)
        assert proof.agent.value == "engineer"
        assert proof.task_id == "T-01"
        assert proof.timestamp  # auto-generated

    def test_custom_timestamp(self, tmp_path):
        evidence = _make_evidence_files(tmp_path, ["log.txt"])
        proof = create_proof(
            agent="qa",
            task_id="T-02",
            claim="Flow passes",
            evidence=evidence,
            reasoning="Tested.",
            timestamp="2026-10-20T10:42:11Z",
        )
        assert proof.timestamp == "2026-10-20T10:42:11Z"

    def test_invalid_agent_raises(self, tmp_path):
        evidence = _make_evidence_files(tmp_path, ["log.txt"])
        with pytest.raises(Exception):  # pydantic ValidationError
            create_proof(
                agent="hacker",
                task_id="T-03",
                claim="X",
                evidence=evidence,
                reasoning="Y",
            )


# ===========================================================================
# validate_proof — accept cases
# ===========================================================================
class TestValidateProofAccept:
    def test_valid_proof_dict(self, tmp_path):
        evidence = _make_evidence_files(tmp_path, ["artifacts/result.json"])
        data = {
            "agent": "qa",
            "task_id": "T-07",
            "claim": "Login flow passes",
            "evidence": evidence,
            "reasoning": "Tested login with valid and invalid credentials.",
            "timestamp": "2026-10-20T10:42:11Z",
        }
        ok, errors = validate_proof(data, base_dir=tmp_path)
        assert ok, f"Expected valid but got errors: {errors}"
        assert errors == []

    def test_valid_proof_model(self, tmp_path):
        evidence = _make_evidence_files(tmp_path, ["build.log"])
        proof = create_proof(
            agent="engineer",
            task_id="T-01",
            claim="Build passes",
            evidence=evidence,
            reasoning="Built successfully.",
        )
        ok, errors = validate_proof(proof, base_dir=tmp_path)
        assert ok, f"Expected valid but got errors: {errors}"

    def test_multiple_evidence_items(self, tmp_path):
        refs = ["artifacts/result.json", "artifacts/screenshot.png", "artifacts/console.log"]
        evidence = _make_evidence_files(tmp_path, refs)
        data = {
            "agent": "qa",
            "task_id": "T-08",
            "claim": "All flows pass",
            "evidence": evidence,
            "reasoning": "Ran all flows.",
            "timestamp": "2026-10-20T11:00:00Z",
        }
        ok, errors = validate_proof(data, base_dir=tmp_path)
        assert ok, f"Expected valid but got errors: {errors}"

    def test_all_agent_names_accepted(self, tmp_path):
        evidence = _make_evidence_files(tmp_path, ["log.txt"])
        for agent in ("planner", "designer", "engineer", "integration", "qa", "critic"):
            data = {
                "agent": agent,
                "task_id": "T-01",
                "claim": "Done",
                "evidence": evidence,
                "reasoning": "Completed.",
                "timestamp": "2026-10-20T12:00:00Z",
            }
            ok, errors = validate_proof(data, base_dir=tmp_path)
            assert ok, f"Agent '{agent}' rejected: {errors}"


# ===========================================================================
# validate_proof — reject cases
# ===========================================================================
class TestValidateProofReject:
    def _base_proof(self, tmp_path) -> dict:
        evidence = _make_evidence_files(tmp_path, ["log.txt"])
        return {
            "agent": "engineer",
            "task_id": "T-01",
            "claim": "Build passes",
            "evidence": evidence,
            "reasoning": "Built.",
            "timestamp": "2026-10-20T10:00:00Z",
        }

    def test_missing_agent(self, tmp_path):
        data = self._base_proof(tmp_path)
        del data["agent"]
        ok, errors = validate_proof(data, base_dir=tmp_path)
        assert not ok
        assert any("agent" in e for e in errors)

    def test_missing_task_id(self, tmp_path):
        data = self._base_proof(tmp_path)
        del data["task_id"]
        ok, errors = validate_proof(data, base_dir=tmp_path)
        assert not ok
        assert any("task_id" in e for e in errors)

    def test_missing_claim(self, tmp_path):
        data = self._base_proof(tmp_path)
        del data["claim"]
        ok, errors = validate_proof(data, base_dir=tmp_path)
        assert not ok
        assert any("claim" in e for e in errors)

    def test_missing_reasoning(self, tmp_path):
        data = self._base_proof(tmp_path)
        del data["reasoning"]
        ok, errors = validate_proof(data, base_dir=tmp_path)
        assert not ok
        assert any("reasoning" in e for e in errors)

    def test_missing_timestamp(self, tmp_path):
        data = self._base_proof(tmp_path)
        del data["timestamp"]
        ok, errors = validate_proof(data, base_dir=tmp_path)
        assert not ok
        assert any("timestamp" in e for e in errors)

    def test_missing_evidence(self, tmp_path):
        data = self._base_proof(tmp_path)
        del data["evidence"]
        ok, errors = validate_proof(data, base_dir=tmp_path)
        assert not ok
        assert any("evidence" in e for e in errors)

    def test_empty_evidence(self, tmp_path):
        data = self._base_proof(tmp_path)
        data["evidence"] = []
        ok, errors = validate_proof(data, base_dir=tmp_path)
        assert not ok
        assert any("at least one" in e for e in errors)

    def test_invalid_agent_name(self, tmp_path):
        data = self._base_proof(tmp_path)
        data["agent"] = "hacker"
        ok, errors = validate_proof(data, base_dir=tmp_path)
        assert not ok
        assert any("Invalid agent" in e for e in errors)

    def test_empty_agent(self, tmp_path):
        data = self._base_proof(tmp_path)
        data["agent"] = ""
        ok, errors = validate_proof(data, base_dir=tmp_path)
        assert not ok

    def test_evidence_ref_not_on_disk(self, tmp_path):
        data = self._base_proof(tmp_path)
        data["evidence"] = [{"type": "log", "ref": "nonexistent/file.log"}]
        ok, errors = validate_proof(data, base_dir=tmp_path)
        assert not ok
        assert any("does not exist" in e for e in errors)

    def test_evidence_missing_type(self, tmp_path):
        data = self._base_proof(tmp_path)
        data["evidence"] = [{"ref": "log.txt"}]
        ok, errors = validate_proof(data, base_dir=tmp_path)
        assert not ok
        assert any("type" in e for e in errors)

    def test_evidence_missing_ref(self, tmp_path):
        data = self._base_proof(tmp_path)
        data["evidence"] = [{"type": "log"}]
        ok, errors = validate_proof(data, base_dir=tmp_path)
        assert not ok
        assert any("ref" in e for e in errors)
