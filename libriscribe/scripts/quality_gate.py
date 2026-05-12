"""Libriscribe release quality gate.

Run from the Libriscribe project root:
    python scripts/quality_gate.py

The gate executes:
1. python -m compileall src
2. python -m pytest -q
3. Practical writing workflow smoke check for libriscribe.web.app

A Markdown report is written to reports/release_gate_report.md.
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter


EXPECTED_VISIBLE_ROUTES = [
    "Projects",
    "Sources",
    "Outline",
    "Editor",
    "Prompts",
    "Quality",
    "Exports",
    "AIConfig",
]

EXPECTED_INTERNAL_ROUTES = [
    "Workspace",
    "Pipeline",
    "Citations",
    "Tools",
    "Settings",
    "Audit",
    "GlobalSettings",
]

SMOKE_CHECK_CODE = r'''
import json
import sys
from pathlib import Path

project_root = Path.cwd()
src_path = project_root / "src"
if str(src_path) not in sys.path:
    sys.path.insert(0, str(src_path))

expected_visible = [
    "Projects",
    "Sources",
    "Outline",
    "Editor",
    "Prompts",
    "Quality",
    "Exports",
    "AIConfig",
]
expected_internal = [
    "Workspace",
    "Pipeline",
    "Citations",
    "Tools",
    "Settings",
    "Audit",
    "GlobalSettings",
]

from libriscribe.web import app

nav_pages = list(getattr(app, "NAV_PAGES", []))
page_renderers = getattr(app, "PAGE_RENDERERS", {})
renderer_keys = list(page_renderers.keys())

missing_from_nav = [page for page in expected_visible if page not in nav_pages]
unexpected_visible_internal_pages = [page for page in expected_internal if page in nav_pages]
expected_all = expected_visible + expected_internal
missing_from_renderers = [page for page in expected_all if page not in page_renderers]
non_callable_renderers = [
    page for page in expected_all
    if page in page_renderers and not callable(page_renderers[page])
]

result = {
    "expected_visible_routes": expected_visible,
    "expected_internal_routes": expected_internal,
    "nav_pages": nav_pages,
    "renderer_keys": renderer_keys,
    "missing_from_nav": missing_from_nav,
    "unexpected_visible_internal_pages": unexpected_visible_internal_pages,
    "missing_from_renderers": missing_from_renderers,
    "non_callable_renderers": non_callable_renderers,
    "passed": not (missing_from_nav or unexpected_visible_internal_pages or missing_from_renderers or non_callable_renderers),
}
print(json.dumps(result, ensure_ascii=False, indent=2))

if not result["passed"]:
    raise SystemExit(1)
'''


def project_root() -> Path:
    """Return the Libriscribe project root regardless of the caller's CWD."""
    return Path(__file__).resolve().parents[1]


def command_to_text(command: list[str]) -> str:
    """Render a subprocess command in a report-friendly form."""
    return " ".join(command)


def run_step(name: str, command: list[str], cwd: Path) -> dict:
    """Run one quality-gate step and return a structured result."""
    started_at = datetime.now(timezone.utc)
    started_perf = perf_counter()

    completed = subprocess.run(
        command,
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
    )

    duration_seconds = perf_counter() - started_perf
    finished_at = datetime.now(timezone.utc)

    return {
        "name": name,
        "command": command_to_text(command),
        "returncode": completed.returncode,
        "passed": completed.returncode == 0,
        "duration_seconds": round(duration_seconds, 3),
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }


def build_report(results: list[dict], root: Path) -> str:
    """Build the Markdown release-gate report."""
    generated_at = datetime.now(timezone.utc).isoformat()
    passed = all(step["passed"] for step in results)
    summary = {
        "generated_at": generated_at,
        "project_root": str(root),
        "passed": passed,
        "steps": [
            {
                "name": step["name"],
                "command": step["command"],
                "passed": step["passed"],
                "returncode": step["returncode"],
                "duration_seconds": step["duration_seconds"],
            }
            for step in results
        ],
    }

    lines = [
        "# Libriscribe Release Gate Report",
        "",
        f"- Generated at: `{generated_at}`",
        f"- Project root: `{root}`",
        f"- Overall status: **{'PASS' if passed else 'FAIL'}**",
        "",
        "## JSON Summary",
        "",
        "```json",
        json.dumps(summary, ensure_ascii=False, indent=2),
        "```",
        "",
        "## Step Results",
        "",
    ]

    for index, step in enumerate(results, start=1):
        lines.extend(
            [
                f"### {index}. {step['name']}",
                "",
                f"- Command: `{step['command']}`",
                f"- Status: **{'PASS' if step['passed'] else 'FAIL'}**",
                f"- Return code: `{step['returncode']}`",
                f"- Duration: `{step['duration_seconds']:.3f}s`",
                f"- Started at: `{step['started_at']}`",
                f"- Finished at: `{step['finished_at']}`",
                "",
                "#### stdout",
                "",
                "```text",
                step["stdout"].rstrip() or "<empty>",
                "```",
                "",
                "#### stderr",
                "",
                "```text",
                step["stderr"].rstrip() or "<empty>",
                "```",
                "",
            ]
        )

    return "\n".join(lines)


def write_report(results: list[dict], root: Path) -> Path:
    """Write reports/release_gate_report.md and return its path."""
    reports_dir = root / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    report_path = reports_dir / "release_gate_report.md"
    report_path.write_text(build_report(results, root), encoding="utf-8")
    return report_path


def main() -> int:
    root = project_root()
    python = sys.executable
    steps = [
        ("Compile source tree", [python, "-m", "compileall", "src"]),
        ("Run pytest suite", [python, "-m", "pytest", "-q"]),
        ("Practical writing workflow smoke check", [python, "-c", SMOKE_CHECK_CODE]),
    ]

    results: list[dict] = []
    for name, command in steps:
        print(f"[quality_gate] RUN  {name}: {command_to_text(command)}", flush=True)
        result = run_step(name, command, root)
        results.append(result)
        status = "PASS" if result["passed"] else "FAIL"
        print(
            f"[quality_gate] {status} {name} "
            f"({result['duration_seconds']:.3f}s, returncode={result['returncode']})",
            flush=True,
        )

    report_path = write_report(results, root)
    overall_passed = all(result["passed"] for result in results)
    print(f"[quality_gate] Report written: {report_path}", flush=True)
    print(f"[quality_gate] Overall status: {'PASS' if overall_passed else 'FAIL'}", flush=True)
    return 0 if overall_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
