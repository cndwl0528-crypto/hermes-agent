import json
import tempfile
import unittest
from pathlib import Path

from hermes_cli.harness_gate import check_tool_gate


def write_plan_artifacts(root: Path, *, allowed_files: list[str], stage: str = "packet_a_execution", packet: str = "A") -> None:
    planning_dir = root / ".planning"
    planning_dir.mkdir(parents=True, exist_ok=True)
    (planning_dir / "active-plan.md").write_text(
        "\n".join(
            [
                "## Event",
                "task",
                "## Function",
                "fn",
                "## Steps",
                "discover",
                "## Verify",
                "targeted",
                "## Closeout",
                "pending",
            ]
        ),
        encoding="utf-8",
    )
    (planning_dir / "harness.json").write_text(
        json.dumps(
            {
                "stage": stage,
                "packet": packet,
                "allowed_files": allowed_files,
            }
        ),
        encoding="utf-8",
    )


class HarnessGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_terminal_blocks_non_read_only_without_plan(self) -> None:
        error = check_tool_gate("terminal", {"command": "npm test"}, str(self.root))
        self.assertIsNotNone(error)
        self.assertIn("plan-first workflow is mandatory", error)

    def test_terminal_allows_read_only_without_plan(self) -> None:
        error = check_tool_gate("terminal", {"command": "rg harness_gate src"}, str(self.root))
        self.assertIsNone(error)

    def test_write_file_allows_planning_files_without_plan(self) -> None:
        error = check_tool_gate("write_file", {"path": ".planning/active-plan.md", "content": "x"}, str(self.root))
        self.assertIsNone(error)

    def test_write_file_allows_locked_packet_file(self) -> None:
        write_plan_artifacts(self.root, allowed_files=["src/app.ts"])
        error = check_tool_gate("write_file", {"path": "src/app.ts", "content": "x"}, str(self.root))
        self.assertIsNone(error)

    def test_write_file_blocks_scope_creep_outside_allowed_files(self) -> None:
        write_plan_artifacts(self.root, allowed_files=["src/app.ts"])
        error = check_tool_gate("write_file", {"path": "src/other.ts", "content": "x"}, str(self.root))
        self.assertIsNotNone(error)
        self.assertIn("scope creep outside locked packet file set", error)

    def test_patch_blocks_scope_creep_outside_allowed_files(self) -> None:
        write_plan_artifacts(self.root, allowed_files=["src/app.ts"])
        error = check_tool_gate(
            "patch",
            {
                "mode": "patch",
                "patch": "*** Begin Patch\n*** Update File: src/other.ts\n@@\n-x\n+y\n*** End Patch\n",
            },
            str(self.root),
        )
        self.assertIsNotNone(error)
        self.assertIn("scope creep outside locked packet file set", error)

    def test_mcp_write_file_uses_harness_gate(self) -> None:
        error = check_tool_gate("mcp_fs_write_file", {"path": "notes.txt", "content": "x"}, str(self.root))
        self.assertIsNotNone(error)
        self.assertIn("plan-first workflow is mandatory", error)

    def test_mcp_write_file_respects_allowed_files(self) -> None:
        write_plan_artifacts(self.root, allowed_files=["notes.txt"])
        allowed = check_tool_gate("mcp_fs_write_file", {"path": "notes.txt", "content": "x"}, str(self.root))
        blocked = check_tool_gate("mcp_fs_write_file", {"path": "other.txt", "content": "x"}, str(self.root))

        self.assertIsNone(allowed)
        self.assertIsNotNone(blocked)
        self.assertIn("scope creep outside locked packet file set", blocked)

    def test_mcp_terminal_uses_harness_gate(self) -> None:
        blocked = check_tool_gate("mcp_shell_terminal", {"command": "npm test"}, str(self.root))
        allowed = check_tool_gate("mcp_shell_terminal", {"command": "pwd"}, str(self.root))

        self.assertIsNotNone(blocked)
        self.assertIn("plan-first workflow is mandatory", blocked)
        self.assertIsNone(allowed)


if __name__ == "__main__":
    unittest.main()
