from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass, asdict
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
    for folder in ("src", "scripts"):
        for path in sorted((root / folder).rglob("*.py")):
            files.append(str(path.relative_to(root)))
    return files


def run_step(root: Path, step: GateStep) -> GateStep:
    started = time.perf_counter()
    env = os.environ.copy()
    env.setdefault("PYTHONIOENCODING", "utf-8")
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


def command_preview(command: list[str]) -> str:
    return " ".join(command)


def write_reports(root: Path, steps: list[GateStep], *, started_at: str, deploy_ready: bool) -> tuple[Path, Path]:
    out_dir = root / "data" / "evals" / "runs"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
    json_path = out_dir / f"production-gate-{stamp}.json"
    md_path = out_dir / f"production-gate-{stamp}.md"
    payload = {
        "started_at": started_at,
        "finished_at": datetime.now().isoformat(timespec="seconds"),
        "deploy_ready": deploy_ready,
        "steps": [asdict(step) for step in steps],
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# Production Gate Report",
        "",
        f"- Started: {started_at}",
        f"- Result: {'deploy-ready' if deploy_ready else 'blocked'}",
        "",
        "## Steps",
    ]
    for step in steps:
        status = "PASS" if step.passed else ("WARN" if not step.required else "FAIL")
        required = "required" if step.required else "advisory"
        lines.append(f"- {status} `{step.name}` ({required}, {step.elapsed_ms} ms)")
        lines.append(f"  - Command: `{command_preview(step.command)}`")
        if not step.passed:
            output = (step.stderr or step.stdout or "").strip()
            if output:
                preview = output[-1800:]
                lines.append("")
                lines.append("```text")
                lines.append(preview)
                lines.append("```")
                lines.append("")

    lines.extend(["", "## Next Actions"])
    failed_required = [step for step in steps if step.required and not step.passed]
    if failed_required:
        lines.append("- Fix the required failures above before deploying.")
        lines.append("- Re-run `python scripts\\run_production_gate.py --root .` after changes.")
    else:
        lines.append("- Gate passed. Rebuild/upload the private index only if corpus content changed.")
        lines.append("- Redeploy or restart Render if code or index changed.")
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return md_path, json_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the production-readiness gate before deploy.")
    parser.add_argument("--root", default=".", help="Repository root")
    parser.add_argument("--skip-corpus-health", action="store_true")
    parser.add_argument("--skip-conversation", action="store_true")
    parser.add_argument("--llm", action="store_true", help="Also run the representative live-model smoke subset.")
    parser.add_argument("--quick", action="store_true", help="Run a small smoke subset for fast iteration.")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    py = sys.executable
    started_at = datetime.now().isoformat(timespec="seconds")
    compile_targets = python_files(root)
    steps: list[GateStep] = [
        GateStep("python_compile", [py, "-m", "py_compile", *compile_targets]),
    ]

    if not args.skip_corpus_health:
        steps.append(
            GateStep(
                "corpus_health",
                [py, "scripts\\audit_corpus_quality.py", "--root", "."],
                required=False,
            )
        )

    if args.quick:
        steps.extend(
            [
                GateStep(
                    "retrieval_eval_quick",
                    [
                        py,
                        "scripts\\run_retrieval_eval.py",
                        "--root",
                        ".",
                        "--ids",
                        "webinar_meeting_cover,todo_current,x1_documents,residence_permit_student,mandarin_programs,consulting_interview",
                    ],
                ),
                GateStep(
                    "whatsapp_smoke_quick",
                    [
                        py,
                        "scripts\\run_whatsapp_smoke.py",
                        "--root",
                        ".",
                        "--ids",
                        "meta_tool_do,international_scholars_webinar,todo_current,x1_visa_docs,residence_permits,mandarin_resources,prompt_injection",
                    ],
                ),
            ]
        )
    else:
        steps.extend(
            [
                GateStep("retrieval_eval", [py, "scripts\\run_retrieval_eval.py", "--root", "."]),
                GateStep("whatsapp_smoke", [py, "scripts\\run_whatsapp_smoke.py", "--root", "."]),
            ]
        )

    if not args.skip_conversation:
        steps.append(GateStep("conversation_smoke", [py, "scripts\\run_conversation_smoke.py", "--root", "."]))

    if args.llm:
        steps.append(
            GateStep(
                "whatsapp_smoke_llm_subset",
                [
                    py,
                    "scripts\\run_whatsapp_smoke.py",
                    "--root",
                    ".",
                    "--llm",
                    "--ids",
                    "international_scholars_webinar,todo_current,x1_visa_docs,residence_permits,mandarin_resources,cover_letter_resources,unsupported_payment_setup,prompt_injection",
                ],
            )
        )

    completed_steps: list[GateStep] = []
    for index, step in enumerate(steps, start=1):
        print(f"[{index}/{len(steps)}] {step.name}", flush=True)
        completed = run_step(root, step)
        completed_steps.append(completed)
        status = "PASS" if completed.passed else ("WARN" if not completed.required else "FAIL")
        print(f"  {status} rc={completed.returncode} elapsed_ms={completed.elapsed_ms}", flush=True)
        if completed.required and not completed.passed:
            break

    deploy_ready = all(step.passed or not step.required for step in completed_steps)
    md_path, json_path = write_reports(root, completed_steps, started_at=started_at, deploy_ready=deploy_ready)
    print(f"Wrote {md_path}")
    print(f"Wrote {json_path}")
    return 0 if deploy_ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
