"""Check action input coverage across local tests and E2E workflows."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


TEXT_SUFFIXES = {".sh", ".py", ".yml", ".yaml", ".md", ".txt"}


def parse_action_inputs(action_file: Path) -> list[str]:
    """Parse top-level `inputs` keys from an action.yml file."""
    lines = action_file.read_text(encoding="utf-8").splitlines()
    inputs_indent: int | None = None
    start = 0
    keys: list[str] = []

    for idx, line in enumerate(lines):
        if re.match(r"^\s*inputs:\s*$", line):
            inputs_indent = len(line) - len(line.lstrip(" "))
            start = idx + 1
            break

    if inputs_indent is None:
        return []

    for line in lines[start:]:
        stripped = line.strip()
        if not stripped or line.lstrip().startswith("#"):
            continue

        indent = len(line) - len(line.lstrip(" "))
        if indent <= inputs_indent:
            break

        match = re.match(r"^(\s+)([A-Za-z0-9_]+):\s*$", line)
        if not match:
            continue

        key_indent = len(match.group(1))
        if key_indent == inputs_indent + 2:
            keys.append(match.group(2))

    return keys


def read_text_if_possible(path: Path) -> str:
    """Read UTF-8 text from path, returning empty string on read errors."""
    if not path.exists() or not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def input_is_covered(input_name: str, corpus: str) -> bool:
    """Check whether an input name appears in test corpus directly or as INPUT_* env."""
    escaped = re.escape(input_name)
    env_name = re.escape(f"INPUT_{input_name.upper()}")
    pattern = re.compile(rf"\b{escaped}\b|\b{env_name}\b")
    return bool(pattern.search(corpus))


def collect_test_corpus(action_repo_dir: Path, e2e_workflow: Path) -> str:
    """Collect all relevant textual test sources for coverage matching."""
    parts: list[str] = []
    if e2e_workflow.exists():
        parts.append(read_text_if_possible(e2e_workflow))

    tests_dir = action_repo_dir / "tests"
    if tests_dir.exists():
        for file_path in sorted(tests_dir.rglob("*")):
            if file_path.is_file() and file_path.suffix in TEXT_SUFFIXES:
                parts.append(read_text_if_possible(file_path))

    return "\n".join(parts)


def load_baseline(path: Path) -> dict[str, list[str]]:
    """Load optional JSON baseline mapping action repo to uncovered inputs."""
    if not path.exists():
        return {}

    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        return {}

    normalized: dict[str, list[str]] = {}
    for key, value in raw.items():
        if isinstance(value, list):
            normalized[key] = sorted(str(v) for v in value)
    return normalized


def build_parser() -> argparse.ArgumentParser:
    """Build command-line argument parser."""
    parser = argparse.ArgumentParser(
        description="Check action input coverage in tests"
    )
    parser.add_argument(
        "--workspace-root",
        required=True,
        help="Workspace root containing action-* repos",
    )
    parser.add_argument(
        "--repo-root",
        required=True,
        help="Path to triglav repository",
    )
    parser.add_argument(
        "--baseline-file",
        required=True,
        help="JSON baseline file for known gaps",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Fail on gaps not present in baseline",
    )
    parser.add_argument(
        "--write-baseline",
        action="store_true",
        help="Write current uncovered gaps to baseline",
    )
    return parser


def collect_results(workspace_root: Path, repo_root: Path) -> dict[str, list[str]]:
    """Collect uncovered input names per action repository."""
    results: dict[str, list[str]] = {}

    for action_repo in sorted(workspace_root.glob("action-*")):
        action_file = action_repo / "action.yml"
        if not action_file.exists():
            continue

        action_name = action_repo.name
        e2e_workflow = repo_root / ".github" / "workflows" / f"e2e-{action_name}.yml"
        inputs = parse_action_inputs(action_file)
        corpus = collect_test_corpus(action_repo, e2e_workflow)
        uncovered = [
            input_name
            for input_name in inputs
            if not input_is_covered(input_name, corpus)
        ]
        results[action_name] = sorted(uncovered)

    return results


def write_baseline_file(results: dict[str, list[str]], baseline_file: Path) -> int:
    """Write JSON baseline and exit successfully."""
    baseline_file.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(results, indent=2, sort_keys=True) + "\n"
    baseline_file.write_text(payload, encoding="utf-8")
    print(f"Wrote baseline: {baseline_file}")
    return 0


def print_report(results: dict[str, list[str]]) -> None:
    """Print human-readable coverage summary."""
    print("Action input coverage report")
    for action_name, uncovered in results.items():
        if uncovered:
            missing = ", ".join(uncovered)
            print(f"- {action_name}: missing {len(uncovered)} -> {missing}")
        else:
            print(f"- {action_name}: fully covered")


def strict_gate(results: dict[str, list[str]], baseline_file: Path) -> int:
    """Apply strict gate against baseline and return process code."""
    baseline = load_baseline(baseline_file)
    has_new_gap = False

    for action_name, uncovered in results.items():
        allowed = set(baseline.get(action_name, []))
        new_gaps = sorted(set(uncovered) - allowed)
        resolved = sorted(allowed - set(uncovered))

        if new_gaps:
            has_new_gap = True
            joined = ", ".join(new_gaps)
            print(
                f"[ERROR] {action_name}: "
                f"new uncovered inputs not in baseline -> {joined}"
            )
        if resolved:
            joined = ", ".join(resolved)
            print(
                f"[INFO] {action_name}: "
                f"baseline can be tightened, now covered -> {joined}"
            )

    return 1 if has_new_gap else 0


def main() -> int:
    """Run coverage check command."""
    parser = build_parser()
    args = parser.parse_args()

    workspace_root = Path(args.workspace_root).resolve()
    repo_root = Path(args.repo_root).resolve()
    baseline_file = Path(args.baseline_file).resolve()

    results = collect_results(workspace_root, repo_root)

    if args.write_baseline:
        return write_baseline_file(results, baseline_file)

    print_report(results)
    if not args.strict:
        return 0

    return strict_gate(results, baseline_file)


if __name__ == "__main__":
    raise SystemExit(main())
