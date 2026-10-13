"""
Tests for JSON Schema validation and the input loader.

Covers:
- Valid inputs pass schema + loader (including the sample_input.json).
- Each required field missing → clear error.
- Invalid enum values → clear error.
- Invalid types → clear error.
- Proof and output schemas validated via jsonschema directly.
"""

from __future__ import annotations

import json
import copy
from pathlib import Path

import jsonschema
import pytest

from lib.models import InputRequest, ProofOfWork, QualityReport, load_input_request

_SCHEMAS_DIR = Path(__file__).resolve().parent.parent.parent / "schemas"
_EXAMPLES_DIR = Path(__file__).resolve().parent.parent.parent / "examples"


# ---- Helpers ---------------------------------------------------------------
def _load_schema(name: str) -> dict:
    with open(_SCHEMAS_DIR / name, "r", encoding="utf-8") as f:
        return json.load(f)


def _valid_input() -> dict:
    """Return a minimal valid input dict."""
    return {
        "brief": "A dashboard for viewing tickets.",
        "api_spec_url": "https://api.example.com/openapi.json",
        "target": "dashboard",
    }


# ===========================================================================
# Input schema + loader: valid cases
# ===========================================================================
class TestInputSchemaValid:
    def test_minimal_valid_input(self):
        req = load_input_request(_valid_input())
        assert isinstance(req, InputRequest)
        assert req.brief == "A dashboard for viewing tickets."
        assert req.target.value == "dashboard"
        assert req.max_iterations == 3  # default

    def test_full_valid_input(self):
        data = _valid_input()
        data["style_hints"] = ["minimal", "dark"]
        data["required_flows"] = ["list items", "create item"]
        data["max_iterations"] = 5
        req = load_input_request(data)
        assert req.style_hints == ["minimal", "dark"]
        assert req.required_flows == ["list items", "create item"]
        assert req.max_iterations == 5

    def test_inline_openapi_object(self):
        data = _valid_input()
        data["api_spec_url"] = {"openapi": "3.0.0", "info": {"title": "Demo"}}
        req = load_input_request(data)
        assert isinstance(req.api_spec_url, dict)

    def test_sample_input_file(self):
        """examples/sample_input.json must validate successfully."""
        req = load_input_request(_EXAMPLES_DIR / "sample_input.json")
        assert req.target.value == "dashboard"
        assert len(req.required_flows) == 4

    def test_all_target_types(self):
        for target in ("dashboard", "form_app", "mixed"):
            data = _valid_input()
            data["target"] = target
            req = load_input_request(data)
            assert req.target.value == target


# ===========================================================================
# Input schema + loader: invalid cases
# ===========================================================================
class TestInputSchemaInvalid:
    def test_missing_brief(self):
        data = _valid_input()
        del data["brief"]
        with pytest.raises(ValueError, match="brief"):
            load_input_request(data)

    def test_missing_api_spec_url(self):
        data = _valid_input()
        del data["api_spec_url"]
        with pytest.raises(ValueError, match="api_spec_url"):
            load_input_request(data)

    def test_missing_target(self):
        data = _valid_input()
        del data["target"]
        with pytest.raises(ValueError, match="target"):
            load_input_request(data)

    def test_invalid_target_enum(self):
        data = _valid_input()
        data["target"] = "mobile_app"
        with pytest.raises(ValueError, match="target"):
            load_input_request(data)

    def test_empty_brief(self):
        data = _valid_input()
        data["brief"] = ""
        with pytest.raises(ValueError, match="brief"):
            load_input_request(data)

    def test_bad_max_iterations_zero(self):
        data = _valid_input()
        data["max_iterations"] = 0
        with pytest.raises(ValueError, match="max_iterations"):
            load_input_request(data)

    def test_bad_max_iterations_negative(self):
        data = _valid_input()
        data["max_iterations"] = -1
        with pytest.raises(ValueError, match="max_iterations"):
            load_input_request(data)

    def test_bad_max_iterations_type(self):
        data = _valid_input()
        data["max_iterations"] = "three"
        with pytest.raises(ValueError, match="max_iterations"):
            load_input_request(data)

    def test_extra_properties_rejected(self):
        data = _valid_input()
        data["unknown_field"] = "oops"
        with pytest.raises(ValueError, match="unknown_field"):
            load_input_request(data)

    def test_file_not_found(self):
        with pytest.raises(ValueError, match="not found"):
            load_input_request("/nonexistent/path.json")

    def test_invalid_json_file(self, tmp_path):
        bad_file = tmp_path / "bad.json"
        bad_file.write_text("not json at all", encoding="utf-8")
        with pytest.raises(ValueError, match="Invalid JSON"):
            load_input_request(bad_file)


# ===========================================================================
# Proof schema: validate via jsonschema
# ===========================================================================
class TestProofSchema:
    SCHEMA = _load_schema("proof.schema.json")

    def _valid_proof(self) -> dict:
        return {
            "agent": "qa",
            "task_id": "T-07",
            "claim": "Login flow passes",
            "evidence": [
                {"type": "test_result", "ref": "artifacts/T-07/result.json"}
            ],
            "reasoning": "Ran the flow successfully.",
            "timestamp": "2026-10-20T10:42:11Z",
        }

    def test_valid_proof(self):
        jsonschema.validate(self._valid_proof(), self.SCHEMA)

    def test_missing_agent(self):
        data = self._valid_proof()
        del data["agent"]
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(data, self.SCHEMA)

    def test_invalid_agent(self):
        data = self._valid_proof()
        data["agent"] = "hacker"
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(data, self.SCHEMA)

    def test_empty_evidence(self):
        data = self._valid_proof()
        data["evidence"] = []
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(data, self.SCHEMA)


# ===========================================================================
# Output schema: validate via jsonschema
# ===========================================================================
class TestOutputSchema:
    SCHEMA = _load_schema("output.schema.json")

    def _valid_output(self) -> dict:
        return {
            "run_id": "run-0007",
            "status": "accepted",
            "iterations": {"total": 5, "by_agent": {"engineer": 3}},
            "gates": {
                "build": {"passed": True, "evidence": "artifacts/build.log"},
                "tests": {"passed": True, "flows_passed": 4, "flows_total": 4},
                "accessibility": {"passed": True, "critical": 0, "serious": 0},
                "quality": {
                    "lighthouse_accessibility": 96,
                    "lighthouse_performance": 88,
                },
                "integration": {"passed": True, "documented_mismatches": 1},
            },
            "revisions": [],
            "unresolved": [],
            "preview_url": "https://labrith-run-0007.example.app",
        }

    def test_valid_output(self):
        jsonschema.validate(self._valid_output(), self.SCHEMA)

    def test_missing_status(self):
        data = self._valid_output()
        del data["status"]
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(data, self.SCHEMA)

    def test_invalid_status(self):
        data = self._valid_output()
        data["status"] = "unknown"
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(data, self.SCHEMA)

    def test_partial_status_with_unresolved(self):
        data = self._valid_output()
        data["status"] = "partial"
        data["unresolved"] = [
            {"issue": "Build keeps failing", "evidence": "artifacts/error.log"}
        ]
        jsonschema.validate(data, self.SCHEMA)

    def test_pydantic_model_round_trip(self):
        """QualityReport pydantic model accepts valid output data."""
        data = self._valid_output()
        report = QualityReport(**data)
        assert report.status.value == "accepted"
        assert report.iterations.total == 5
