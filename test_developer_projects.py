"""Security and integration tests for XemAi developer-mode phase 1."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from app.developer_projects import DeveloperProjects, ProjectError
from app.tools import ToolRegistry


class NoopLogger:
    def info(self, *args, **kwargs):
        pass

    def warning(self, *args, **kwargs):
        pass


def test_explicit_project_readonly_access():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        workspace = root / "xemai" / "workspace"
        workspace.mkdir(parents=True)
        project = root / "projects" / "XemTV"
        (project / "android-app").mkdir(parents=True)
        (project / ".git").mkdir()
        (project / "android-app" / "MainActivity.kt").write_text(
            "class MainActivity {\n  // sidebar focus\n}\n", encoding="utf-8"
        )
        (project / ".env").write_text("PRIVATE_KEY=should-not-leak", encoding="utf-8")
        (project / "android-app" / "secret-token.txt").write_text("secret", encoding="utf-8")
        (project / "android-app" / "binary.png").write_bytes(b"\x89PNG\x00")
        (project / "android-app" / "big.kt").write_text("X" * 400001, encoding="utf-8")
        other = root / "outside.kt"
        other.write_text("should-not-see", encoding="utf-8")
        projects = DeveloperProjects([{"id": "xemtv", "path": str(project)}], workspace=workspace)

        assert projects.enabled
        assert projects.projects() == [{"project": "xemtv", "available": True, "mode": "read-only"}]
        listed = projects.list_files("xemtv")
        assert "android-app" in [p["path"] for p in listed["items"]]
        assert ".git" not in [p["path"] for p in listed["items"]]
        assert ".env" not in [p["path"] for p in listed["items"]]
        text = projects.read_file("xemtv", "android-app/MainActivity.kt")
        assert "sidebar focus" in text["content"]
        assert text["read_only"] is True
        assert projects.search("xemtv", "SIDEBAR")["matches"][0]["line"] == 2
        for relative in (
            "../outside.kt", "/etc/passwd", "android-app/../../outside.kt",
            ".git/config", ".env", "android-app/secret-token.txt",
            "android-app/binary.png", "android-app/big.kt",
        ):
            try:
                projects.read_file("xemtv", relative)
            except ProjectError:
                pass
            else:
                raise AssertionError("Read-only project should reject " + relative)
        assert not hasattr(projects, "write_file")
        if (project / "android-app" / "outside.kt").exists():
            raise AssertionError("Project inspector changed the source repository.")

        link = project / "linked.kt"
        try:
            link.symlink_to(other)
        except (OSError, NotImplementedError):
            pass  # Windows may require developer mode for symlink creation.
        else:
            try:
                projects.read_file("xemtv", "linked.kt")
            except ProjectError:
                pass
            else:
                raise AssertionError("Project inspector followed a symlink.")


def test_project_cannot_be_same_as_writable_workspace():
    with tempfile.TemporaryDirectory() as temporary:
        workspace = Path(temporary) / "workspace"
        workspace.mkdir()
        projects = DeveloperProjects(
            [{"id": "xemtv", "path": str(workspace / "xemtv")}],
            workspace=workspace,
        )
        assert not projects.enabled
        assert not DeveloperProjects(
            [{"id": "xemtv", "path": str(workspace.parent)}],
            workspace=workspace,
        ).enabled


def test_tool_registry_readonly_interface():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        root.joinpath("data").mkdir()
        project = root / "my-project"
        project.mkdir()
        project.joinpath("README.md").write_text("Test XemTV project", encoding="utf-8")
        registry = ToolRegistry(root, root / "data", NoopLogger())
        registry.developer = DeveloperProjects(
            [{"id": "xemtv", "path": str(project)}], workspace=registry.workspace
        )
        names = {entry["function"]["name"] for entry in registry.definitions()}
        assert {"dev_projects", "dev_list", "dev_read", "dev_search"} <= names
        body = json.loads(registry.execute("dev_read", {
            "project": "xemtv", "path": "README.md",
        }))
        assert body["ok"] is True
        assert body["result"]["read_only"] is True
        assert "Test XemTV project" in body["result"]["content"]
        assert json.loads(registry.execute("dev_read", {
            "project": "other", "path": "README.md",
        }))["ok"] is False
        registry.developer = DeveloperProjects([], workspace=registry.workspace)
        assert "dev_read" not in {item["function"]["name"] for item in registry.definitions()}
        assert json.loads(registry.execute("dev_read", {
            "project": "xemtv", "path": "README.md",
        }))["ok"] is False


if __name__ == "__main__":
    test_explicit_project_readonly_access()
    test_project_cannot_be_same_as_writable_workspace()
    test_tool_registry_readonly_interface()
    print("Developer-mode read-only tests passed.")
