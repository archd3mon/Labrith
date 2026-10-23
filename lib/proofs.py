"""
Proof-of-work creation and validation.

Every agent output must carry a proof-of-work record (Design Doc §6).
The Planner rejects outputs without one.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Union

from lib.models import AgentName, EvidenceItem, ProofOfWork

# Valid agent names as a set for quick membership checks.
_VALID_AGENTS = {a.value for a in AgentName}


def create_proof(
    agent: str,
    task_id: str,
    claim: str,
    evidence: list[dict[str, str]],
    reasoning: str,
    timestamp: Optional[str] = None,
) -> ProofOfWork:
    """Create a valid ProofOfWork record.

    Args:
        agent: One of the six agent names.
        task_id: Task identifier (e.g. "T-07").
        claim: What the agent claims to have done.
        evidence: List of dicts, each with "type" and "ref" keys.
        reasoning: Short reasoning note.
        timestamp: ISO 8601 timestamp; defaults to current UTC time.

    Returns:
        A validated ProofOfWork instance.

    Raises:
        ValueError / pydantic.ValidationError on invalid data.
    """
    if timestamp is None:
        timestamp = datetime.now(timezone.utc).isoformat()

    evidence_items = [EvidenceItem(**e) for e in evidence]

    return ProofOfWork(
        agent=agent,
        task_id=task_id,
        claim=claim,
        evidence=evidence_items,
        reasoning=reasoning,
        timestamp=timestamp,
    )


def validate_proof(
    proof: Union[dict, ProofOfWork],
    base_dir: Optional[Path] = None,
) -> tuple[bool, list[str]]:
    """Validate a proof-of-work record.

    Checks:
    1. All required fields are present and non-empty.
    2. ``agent`` is one of the six canonical agent names.
    3. ``evidence`` is a non-empty list of objects with ``type`` and ``ref``.
    4. Each evidence ``ref`` exists on disk (resolved against *base_dir*).

    Args:
        proof: A dict or ProofOfWork instance to validate.
        base_dir: Directory to resolve evidence ref paths against.
                  If None, refs are checked as-is (absolute or cwd-relative).

    Returns:
        (is_valid, errors) — True with empty list on success, False with a
        list of human-readable error strings on failure.
    """
    errors: list[str] = []

    # ---- Normalise to dict ---------------------------------------------------
    if isinstance(proof, ProofOfWork):
        data = proof.model_dump()
    elif isinstance(proof, dict):
        data = proof
    else:
        return False, [f"Expected dict or ProofOfWork, got {type(proof).__name__}"]

    # ---- Required scalar fields -----------------------------------------------
    required_fields = ["agent", "task_id", "claim", "reasoning", "timestamp"]
    for field in required_fields:
        value = data.get(field)
        if value is None:
            errors.append(f"Missing required field: '{field}'")
        elif isinstance(value, str) and not value.strip():
            errors.append(f"Field '{field}' must not be empty")

    # ---- Agent name -----------------------------------------------------------
    agent_val = data.get("agent")
    if agent_val is not None and agent_val not in _VALID_AGENTS:
        errors.append(
            f"Invalid agent '{agent_val}'. Must be one of: {sorted(_VALID_AGENTS)}"
        )

    # ---- Evidence list --------------------------------------------------------
    evidence = data.get("evidence")
    if evidence is None:
        errors.append("Missing required field: 'evidence'")
    elif not isinstance(evidence, list):
        errors.append("Field 'evidence' must be a list")
    elif len(evidence) == 0:
        errors.append("Field 'evidence' must contain at least one item")
    else:
        for i, item in enumerate(evidence):
            if not isinstance(item, dict):
                errors.append(f"evidence[{i}]: expected an object, got {type(item).__name__}")
                continue
            if not item.get("type"):
                errors.append(f"evidence[{i}]: missing or empty 'type'")
            ref = item.get("ref")
            if not ref:
                errors.append(f"evidence[{i}]: missing or empty 'ref'")
            else:
                # Only check file existence for local paths (skip URLs and in-memory refs)
                if not ref.startswith(("http://", "https://")):
                    ref_path = Path(ref)
                    if base_dir is not None:
                        ref_path = base_dir / ref_path
                    if not ref_path.exists():
                        errors.append(
                            f"evidence[{i}]: ref '{ref}' does not exist on disk"
                            + (f" (resolved to {ref_path})" if base_dir else "")
                        )

    return (len(errors) == 0, errors)
