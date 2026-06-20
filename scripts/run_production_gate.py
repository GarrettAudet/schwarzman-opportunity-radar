from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path


@dataclass
class GateStep:
    name: str
    command: list[str]
    required: bool = True
    returncode: int = 0
    elapsed_ms: int = 0
    stdout: str = ""
    stderr: str = ""

    @property
    def passed(self) -> bool:
        return self.returncode == 0


def python_files(root: Path) -> list[str]:
    files = []
    for folder in ("src", "scripts", "tests"):
        target = root / folder
        if target.exists():
            files.extend(str(path.relative_to(root)) for path in sorted(target.rglob("*.py")))
    return files


def run_step(root: Path, step: GateStep) -> GateStep:
    started = time.perf_counter()
    env = os.environ.copy()
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env["PYTHONPATH"] = str(root / "src")
    completed = subprocess.run(
        step.command,
        cwd=root,
        env=env,
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
    )
    step.elapsed_ms = int((time.perf_counter() - started) * 1000)
    step.returncode = completed.returncode
    step.stdout = completed.stdout
    step.stderr = completed.stderr
    return step


def write_report(root: Path, steps: list[GateStep], started_at: str, ready: bool) -> Path:
    out_dir = root / "data" / "runs"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
    json_path = out_dir / f"production-gate-{stamp}.json"
    md_path = out_dir / f"production-gate-{stamp}.md"
    json_path.write_text(
        json.dumps(
            {
                "started_at": started_at,
                "finished_at": datetime.now().isoformat(timespec="seconds"),
                "deploy_ready": ready,
                "steps": [asdict(step) for step in steps],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    lines = ["# OpportunityRadar Production Gate", "", f"- Result: {'deploy-ready' if ready else 'blocked'}", "", "## Steps"]
    for step in steps:
        status = "PASS" if step.passed else ("WARN" if not step.required else "FAIL")
        lines.append(f"- {status} `{step.name}` ({step.elapsed_ms} ms)")
        if not step.passed:
            preview = (step.stderr or step.stdout or "").strip()[-1800:]
            if preview:
                lines.extend(["", "```text", preview, "```", ""])
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return md_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the OpportunityRadar production-readiness gate.")
    parser.add_argument("--root", default=".", help="Repository root")
    args = parser.parse_args()
    root = Path(args.root).resolve()
    py = sys.executable
    started_at = datetime.now().isoformat(timespec="seconds")
    steps = [
        GateStep("python_compile", [py, "-m", "py_compile", *python_files(root)]),
        GateStep("unit_tests", [py, "-m", "unittest", "discover", "-s", "tests"]),
        GateStep(
            "fixture_discovery_smoke",
            [
                py,
                "scripts\\run_discovery.py",
                "--root",
                ".",
                "--sources",
                "tests\\fixtures\\sources.fixture.json",
                "--conditions",
                "tests\\fixtures\\conditions.fixture.json",
                "--deterministic-fallback",
                "--json",
            ],
        ),
        GateStep(
            "fixture_digest_smoke",
            [
                py,
                "scripts\\run_weekly_digest.py",
                "--root",
                ".",
                "--sources",
                "tests\\fixtures\\sources.fixture.json",
                "--deterministic-fallback",
                "--include-seen",
                "--json",
            ],
        ),
    ]
    completed = []
    for index, step in enumerate(steps, start=1):
        print(f"[{index}/{len(steps)}] {step.name}", flush=True)
        completed_step = run_step(root, step)
        completed.append(completed_step)
        print(f"  {'PASS' if completed_step.passed else 'FAIL'} rc={completed_step.returncode}", flush=True)
        if completed_step.required and not completed_step.passed:
            break
    ready = all(step.passed or not step.required for step in completed)
    report_path = write_report(root, completed, started_at, ready)
    print(f"Wrote {report_path}")
    return 0 if ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
