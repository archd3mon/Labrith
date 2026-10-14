"""
Tests for tools/sandbox.py.

Covers:
- Sandbox initialization creates runs/<run_id>/app.
- Template scaffolding.
- write_file and read_file.
- Path-escape detection and refusal (ValueError / PathEscapeError).
- Command execution with output saving to artifacts/.
- Timeout handling.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from tools.sandbox import CommandResult, PathEscapeError, Sandbox


@pytest.fixture
def test_sandbox(tmp_path: Path) -> Sandbox:
    template_dir = tmp_path / "mock_template"
    template_dir.mkdir()
    (template_dir / "package.json").write_text('{"name": "mock-app"}', encoding="utf-8")
    (template_dir / "src").mkdir()
    (template_dir / "src" / "App.tsx").write_text("export const App = () => null;", encoding="utf-8")

    return Sandbox(
        run_id="run-test-01",
        base_dir=tmp_path / "runs",
        template_dir=template_dir,
        artifact_dir=tmp_path / "artifacts",
    )


class TestSandboxBasics:
    def test_directory_structure(self, test_sandbox: Sandbox):
        assert test_sandbox.app_dir.exists()
        assert test_sandbox.artifact_dir.exists()
        assert (test_sandbox.app_dir / "package.json").exists()
        assert (test_sandbox.app_dir / "src" / "App.tsx").exists()

    def test_write_and_read_file(self, test_sandbox: Sandbox):
        test_sandbox.write_file("src/components/Button.tsx", "export const Button = () => <button />;")
        content = test_sandbox.read_file("src/components/Button.tsx")
        assert content == "export const Button = () => <button />;"

    def test_read_nonexistent_file_raises_error(self, test_sandbox: Sandbox):
        with pytest.raises(FileNotFoundError):
            test_sandbox.read_file("src/NonExistent.tsx")

    def test_reinstantiation_preserves_components(self, test_sandbox: Sandbox):
        test_sandbox.write_file("src/components/Header.tsx", "export const Header = () => <header />;")
        # Reinstantiate sandbox with identical run_id
        reloaded = Sandbox(
            run_id=test_sandbox.run_id,
            base_dir=test_sandbox.base_dir,
            template_dir=test_sandbox.template_dir,
            artifact_dir=test_sandbox.artifact_dir.parent,
        )
        assert (reloaded.app_dir / "src" / "components" / "Header.tsx").exists()
        assert reloaded.read_file("src/components/Header.tsx") == "export const Header = () => <header />;"


class TestPathEscape:
    def test_relative_escape_write(self, test_sandbox: Sandbox):
        with pytest.raises(ValueError):
            test_sandbox.write_file("../escaped.txt", "malicious")

    def test_nested_relative_escape_write(self, test_sandbox: Sandbox):
        with pytest.raises(ValueError):
            test_sandbox.write_file("sub/../../escaped.txt", "malicious")

    def test_relative_escape_read(self, test_sandbox: Sandbox):
        with pytest.raises(ValueError):
            test_sandbox.read_file("../escaped.txt")

    def test_absolute_escape_write(self, test_sandbox: Sandbox, tmp_path: Path):
        outside_file = tmp_path / "outside.txt"
        with pytest.raises(ValueError):
            test_sandbox.write_file(outside_file, "malicious")

    def test_absolute_escape_read(self, test_sandbox: Sandbox, tmp_path: Path):
        outside_file = tmp_path / "outside.txt"
        outside_file.write_text("data", encoding="utf-8")
        with pytest.raises(ValueError):
            test_sandbox.read_file(outside_file)

    def test_empty_path_raises(self, test_sandbox: Sandbox):
        with pytest.raises(ValueError):
            test_sandbox.write_file("", "data")


class TestCommandExecution:
    def test_run_command_success(self, test_sandbox: Sandbox):
        cmd = [sys.executable, "-c", "print('hello from sandbox')"]
        result = test_sandbox.run(cmd, log_name="test_cmd.log")

        assert isinstance(result, CommandResult)
        assert result.exit_code == 0
        assert "hello from sandbox" in result.stdout
        assert result.log_path is not None
        assert Path(result.log_path).exists()
        assert "hello from sandbox" in Path(result.log_path).read_text(encoding="utf-8")

    def test_run_command_failure(self, test_sandbox: Sandbox):
        cmd = [sys.executable, "-c", "import sys; sys.stderr.write('fatal error'); sys.exit(2)"]
        result = test_sandbox.run(cmd, log_name="error.log")

        assert result.exit_code == 2
        assert "fatal error" in result.stderr
        assert result.log_path is not None
        assert "fatal error" in Path(result.log_path).read_text(encoding="utf-8")

    def test_run_command_timeout(self, test_sandbox: Sandbox):
        cmd = [sys.executable, "-c", "import time; time.sleep(5)"]
        result = test_sandbox.run(cmd, timeout=1, log_name="timeout.log")

        assert result.exit_code == 124
        assert "timed out" in result.stderr
        assert result.log_path is not None
        assert "timed out" in Path(result.log_path).read_text(encoding="utf-8")
