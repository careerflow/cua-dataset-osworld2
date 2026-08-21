#!/usr/bin/env python3
"""Install Careerflow OSWorld tasks into an OSWorld-V2 clone.

Usage (from anywhere):

    uv run --directory /path/to/OSWorld-V2 python \\
        /path/to/cua-dataset-osworld2/install.py --target /path/to/OSWorld-V2

The target defaults to the parent of this package's directory, so copying this
setup directory into an OSWorld-V2 clone and running ``uv run python
cua-dataset-osworld2/install.py`` does the right thing.

This package ships no tasks. Extract the Careerflow task zip into
``tasks/`` beside this file first — one ``tasks/task_<id>/task_<id>.py`` plus
its ``assets/`` per task, same layout regardless of how many tasks the zip
contains. The installer discovers every task under ``tasks/`` at run time;
nothing here hardcodes an id, a count, or a naming scheme.

What it does, all idempotent:

1. discovers every task under ``tasks/`` and copies its class plus the shared
   ``document_flush`` helper into ``evaluation_examples/task_class/``;
2. copies each task's assets into ``cache/osworld_v2_assets/task_<id>/``;
3. ensures ``.env`` declares ``WEBSITE_HOST_SUFFIX``;
4. applies the mocked-website HTTPS patch, and **fails** rather than warning if
   it does not land (skip with ``--no-patches``);
5. verifies the result: the clone carries the patched website behaviour, every
   task imports, and every source asset digest matches - so a packaging fault
   fails here instead of showing up as a low agent score with no visible cause;
6. prints the exact environment exports and run command to use next.

The only upstream file modified is ``desktop_env/controllers/website.py``,
via ``patches/``; nothing else outside those paths is touched. The suite is
strictly pinned to upstream commit 8b6b596 (2026-08-14). The installer rejects
every other revision before it writes anything to the target checkout.
"""

from __future__ import annotations

import argparse
import filecmp
import hashlib
import importlib.util
import inspect
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

PACKAGE = Path(__file__).resolve().parent
DEFAULT_HOST_SUFFIX = "site.hku.icu"

# Assets owned by upstream tasks that some Careerflow tasks reuse. Not shipped
# here (81 MB for the one currently known), but a local asset snapshot must
# still contain them. Keyed by task id; harmless if that id is absent.
UPSTREAM_ASSET_REPO = "xlangai/osworld_v2_assets_gated"
UPSTREAM_ASSETS = {"CF6": "task_059/GeoGebra-Linux-Portable-5-4-925-3.tar.bz2"}

# The upstream revision this package was built and end-to-end verified against.
#   git clone https://github.com/xlang-ai/OSWorld-V2 && git checkout <commit>
VERIFIED_UPSTREAM_COMMIT = "8b6b59660b59832a42a345db8f86fa9f98c37573"
VERIFIED_UPSTREAM_DATE = "2026-08-14"
PATCH_TARGET = "desktop_env/controllers/website.py"

# Tasks known to seed a mocked website and so need the HTTPS compatibility
# patch. Harmless if a discovered task id is not in this set.
WEBSITE_TASKS = {"CF1", "CF2", "CF4", "CF5"}

# Evaluator fixtures some tasks read directly from the checkout rather than
# through asset(). Harmless if a discovered task id is not in this dict.
EVALUATOR_FIXTURES = {
    "CF3": ["cache/osworld_v2_assets/task_CF3/T11_Financial_Close/Q4_AP_Close_Workbook.xlsx"],
    "CF5": ["cache/osworld_v2_assets/task_CF5/teamchat_state.json"],
    "CF6": ["cache/osworld_v2_assets/task_CF6/carafe_profile_truth.json",
            "cache/osworld_v2_assets/task_CF6/carafe_edge_points.json"],
    "CF7": [
        "cache/osworld_v2_assets/task_CF7/ground_truth/Completed_Form_8843_2025.pdf",
        "cache/osworld_v2_assets/task_CF7/ground_truth/Completed_Form_1040NR_2025.pdf",
        "cache/osworld_v2_assets/task_CF7/ground_truth/Completed_Schedule1_2025.pdf",
        "cache/osworld_v2_assets/task_CF7/ground_truth/Completed_Form_CA540NR_2025.pdf",
    ],
    "CF8": [
        "cache/osworld_v2_assets/task_CF8/FY26_Operating_Model_Review.xlsx",
        "cache/osworld_v2_assets/task_CF8/ground_truth/FY26_Operating_Model_Review_SOLVED.xlsx",
        "cache/osworld_v2_assets/task_CF8/ground_truth/digests.json",
    ],
    "CF9": [
        "cache/osworld_v2_assets/task_CF9/ground_truth/digests.json",
        "cache/osworld_v2_assets/task_CF9/ground_truth/reference_style_target.png",
    ],
    "CF10": [
        "cache/osworld_v2_assets/task_CF10/task_1015_golden_oracle.pptx",
    ],
}

# Files never copied into the clone.
SKIP_NAMES = {"__pycache__", ".DS_Store", ".pytest_cache"}

TASK_DIR_RE = re.compile(r"^task_(.+)$")


def _log(message: str) -> None:
    print(f"[install] {message}")


def _fail(message: str) -> None:
    print(f"[install] ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def discover_task_ids() -> list[str]:
    """Find every task under ``tasks/`` — any id, any count, any naming.

    A task is a directory ``tasks/task_<id>/`` containing ``task_<id>.py``.
    The installer hardcodes no ids: this repository ships infrastructure
    only, and the task zip is dropped into ``tasks/`` separately.
    """
    tasks_dir = PACKAGE / "tasks"
    if not tasks_dir.is_dir():
        _fail(
            f"{tasks_dir} does not exist. Extract the Careerflow task zip into it first "
            f"(one tasks/task_<id>/task_<id>.py plus assets/ per task)."
        )
    ids = []
    for entry in sorted(tasks_dir.iterdir()):
        if not entry.is_dir():
            continue
        match = TASK_DIR_RE.match(entry.name)
        if not match:
            continue
        task_id = match.group(1)
        if (entry / f"task_{task_id}.py").is_file():
            ids.append(task_id)
    if not ids:
        _fail(
            f"no tasks found under {tasks_dir}. Expected tasks/task_<id>/task_<id>.py "
            f"for at least one id."
        )
    return ids


def _copy_file(source: Path, destination: Path, *, counters: dict) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and filecmp.cmp(source, destination, shallow=False):
        counters["unchanged"] += 1
        return
    counters["written" if not destination.exists() else "overwritten"] += 1
    shutil.copy2(source, destination)


def _copy_tree(source: Path, destination: Path, *, counters: dict) -> None:
    for item in sorted(source.rglob("*")):
        if any(part in SKIP_NAMES for part in item.relative_to(source).parts):
            continue
        if item.is_dir():
            continue
        _copy_file(item, destination / item.relative_to(source), counters=counters)


def validate_target(target: Path) -> None:
    """Refuse to install into anything that is not an OSWorld-V2 checkout."""
    required = [
        Path("run.py"),
        Path("task_loader.py"),
        Path("desktop_env/task_base.py"),
        Path("desktop_env/file_source.py"),
        Path("evaluation_examples/task_class"),
    ]
    missing = [str(item) for item in required if not (target / item).exists()]
    if missing:
        _fail(
            f"{target} does not look like an OSWorld-V2 clone; missing: {', '.join(missing)}\n"
            f"           pass the clone root explicitly, e.g.\n"
            f"           uv run python {Path(__file__).name} --target /path/to/OSWorld-V2"
        )


def install_tasks(target: Path, task_ids: list[str], counters: dict) -> None:
    class_dir = target / "evaluation_examples" / "task_class"
    _copy_file(PACKAGE / "shared" / "document_flush.py", class_dir / "document_flush.py",
               counters=counters)
    for task_id in task_ids:
        source = PACKAGE / "tasks" / f"task_{task_id}"
        _copy_file(source / f"task_{task_id}.py", class_dir / f"task_{task_id}.py",
                   counters=counters)
        # cache/osworld_v2_assets/ is what asset() serves to the VM and what the
        # evaluators read back. Paths are fixed; do not relocate them.
        _copy_tree(source / "assets",
                   target / "cache" / "osworld_v2_assets" / f"task_{task_id}",
                   counters=counters)


def ensure_env_file(target: Path, host_suffix: str) -> None:
    """``desktop_env/controllers/website.py`` raises at import without this."""
    env_path = target / ".env"
    lines = env_path.read_text(encoding="utf-8").splitlines() if env_path.is_file() else []
    for line in lines:
        if line.strip().startswith("WEBSITE_HOST_SUFFIX="):
            _log(f".env already sets {line.strip()}")
            return
    lines.append(f"WEBSITE_HOST_SUFFIX={host_suffix}")
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    _log(f".env: added WEBSITE_HOST_SUFFIX={host_suffix}")


def require_verified_upstream_commit(target: Path) -> None:
    """Require the exact OSWorld revision against which this pack was tested.

    The website compatibility patch is intentionally line-based.  Applying it
    to a newer upstream revision can either fail or, worse, hide a behavioral
    incompatibility behind a successful copy of the task files.  Fail before
    any installer side effect instead of attempting a best-effort port.
    """
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=target,
                          capture_output=True, text=True)
    if head.returncode != 0:
        _fail(
            f"{target} is not a Git checkout, so its OSWorld revision cannot be verified.\n"
            f"           Clone {VERIFIED_UPSTREAM_COMMIT} and retry."
        )
    current = head.stdout.strip()
    if current == VERIFIED_UPSTREAM_COMMIT:
        _log(f"clone is at the verified upstream commit {current[:10]}")
        return
    _fail(
        f"unsupported OSWorld-V2 commit {current}. This task pack is pinned to "
        f"{VERIFIED_UPSTREAM_COMMIT} ({VERIFIED_UPSTREAM_DATE}) because its website "
        f"compatibility patch is tested only there.\n"
        f"           Run: git -C {target} checkout {VERIFIED_UPSTREAM_COMMIT}"
    )


def apply_patches(target: Path) -> list[str]:
    """Apply patches/*.patch, returning a problem per patch that did not land."""
    problems: list[str] = []
    for patch in sorted((PACKAGE / "patches").glob("*.patch")):
        reversed_check = subprocess.run(
            ["git", "apply", "--check", "--reverse", str(patch)],
            cwd=target, capture_output=True, text=True,
        )
        if reversed_check.returncode == 0:
            _log(f"patch already applied: {patch.name}")
            continue
        applied = subprocess.run(
            ["git", "apply", str(patch)], cwd=target, capture_output=True, text=True,
        )
        if applied.returncode == 0:
            _log(f"applied patch: {patch.name}")
            continue
        problems.append(
            f"{patch.name} did not apply: {applied.stderr.strip() or 'unknown error'}. "
            f"Upstream has probably changed {PATCH_TARGET}; port the patch by hand "
            f"(it is ~20 lines) or fix the behaviour it provides, then re-run this installer."
        )
    return problems


def check_patched_behaviour(target: Path, task_ids: list[str]) -> list[str]:
    """Verify the website fixes are present however they got there.

    Checking behaviour rather than "did git apply succeed" means a clone that
    already carries an equivalent upstream fix passes, while a clone where the
    patch silently failed is caught. Without these two properties the mocked-
    website tasks fail setup with a redirect error.
    """
    if not any(task_id in WEBSITE_TASKS for task_id in task_ids):
        return []
    source_path = target / PATCH_TARGET
    if not source_path.is_file():
        return [f"{PATCH_TARGET} is missing from the clone"]

    source = source_path.read_text(encoding="utf-8")
    probe = source[source.find("def _select_website_scheme"):source.find("def build_website_url")]
    problems = []
    if "verify=False" not in probe:
        problems.append(
            f"{PATCH_TARGET}: the HTTPS scheme probe still verifies certificates. The mocked "
            f"apps use self-signed certificates, so setup for {', '.join(sorted(WEBSITE_TASKS))} "
            f"will fall back to HTTP and fail with a redirect error."
        )
    if "timeout=3" in probe:
        problems.append(
            f"{PATCH_TARGET}: the HTTPS scheme probe still gives up after 3 seconds. The result "
            f"is cached per process, so one slow response sends the whole run to HTTP."
        )
    state_block = source[source.find("def prepare_stateful_website_urls"):]
    if "allow_redirects=False" not in state_block:
        problems.append(
            f"{PATCH_TARGET}: state requests still follow redirects silently, so a dropped "
            f"state payload scores as an agent failure instead of raising."
        )
    return problems


def fetch_upstream_assets(target: Path, task_ids: list[str]) -> list[str]:
    """Fetch the upstream assets some tasks reuse but do not ship.

    ``OSWORLD_FILE_BASE_URL`` names one location, so once it points at the local
    snapshot every asset a task requests must exist there — including assets
    that belong to upstream tasks.
    """
    problems: list[str] = []
    for task_id, relative in UPSTREAM_ASSETS.items():
        if task_id not in task_ids:
            continue
        destination = target / "cache" / "osworld_v2_assets" / relative
        if destination.is_file() and destination.stat().st_size > 0:
            _log(f"upstream asset present: {relative}")
            continue
        # Shipped in the task's own package, so a clone with no network still works.
        bundled = PACKAGE / "tasks" / f"task_{task_id}" / "upstream_assets" / relative
        if bundled.is_file():
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(bundled, destination)
            _log(f"installed bundled upstream asset: {relative} "
                 f"({destination.stat().st_size // (1024 * 1024)} MB)")
            continue

        pattern = relative  # exact file: the upstream task dir holds much more this task never uses
        manual = (f"python scripts/tools/download_osworld_v2_assets.py "
                  f"--allow-pattern '{pattern}'")
        downloader = target / "scripts" / "tools" / "download_osworld_v2_assets.py"
        if not downloader.is_file():
            problems.append(f"task {task_id}: upstream asset {relative} is missing and this clone "
                            f"has no {downloader.relative_to(target)}; fetch it by hand")
            continue

        _log(f"fetching upstream asset via the clone's own downloader (once): {relative}")
        # The downloader builds an unauthenticated HfApi() and never reads .env,
        # so a token that only lives there looks like "no access". Pass it on.
        _load_dotenv(target)
        env = dict(os.environ)
        token = env.get("HF_TOKEN") or env.get("HUGGINGFACE_HUB_TOKEN")
        if token:
            env["HF_TOKEN"] = env["HUGGINGFACE_HUB_TOKEN"] = token
        result = subprocess.run(
            [sys.executable, str(downloader), "--allow-pattern", pattern],
            cwd=target, capture_output=True, text=True, env=env,
        )
        if destination.is_file() and destination.stat().st_size > 0:
            _log(f"fetched {relative} ({destination.stat().st_size // (1024 * 1024)} MB)")
            continue
        detail = (result.stderr or result.stdout or "").strip().splitlines()
        problems.append(
            f"task {task_id}: could not fetch upstream asset {relative}"
            + (f": {detail[-1]}" if detail else "")
            + f". It lives in the gated dataset {UPSTREAM_ASSET_REPO}, so accept its terms on "
              f"Hugging Face and set HF_TOKEN, then run: {manual}"
        )
    return problems


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_dotenv(target: Path) -> None:
    """website.py raises at import time when WEBSITE_HOST_SUFFIX is unset."""
    env_path = target / ".env"
    if not env_path.is_file():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


def verify_install(target: Path, task_ids: list[str]) -> list[str]:
    """Import every task and confirm the evaluator can read what it needs.

    Every problem found here would otherwise surface as a low agent score with
    no visible cause, so this runs by default after installing.
    """
    problems: list[str] = []

    problems.extend(check_patched_behaviour(target, task_ids))

    _load_dotenv(target)
    if not os.environ.get("WEBSITE_HOST_SUFFIX"):
        problems.append("WEBSITE_HOST_SUFFIX is unset; the mocked-website tasks cannot import")
    if str(target) not in sys.path:
        sys.path.insert(0, str(target))

    try:
        from desktop_env.task_base import BaseTask
    except Exception as error:  # noqa: BLE001
        problems.append(f"cannot import desktop_env from {target}: {error}")
        return problems

    for task_id in task_ids:
        module_path = target / "evaluation_examples" / "task_class" / f"task_{task_id}.py"
        if not module_path.is_file():
            problems.append(f"task {task_id}: {module_path} was not written")
            continue
        try:
            spec = importlib.util.spec_from_file_location(f"_verify_task_{task_id}", module_path)
            module = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = module
            spec.loader.exec_module(module)
        except Exception as error:  # noqa: BLE001
            problems.append(f"task {task_id}: import failed: {type(error).__name__}: {error}")
            continue

        classes = {
            id(obj): obj for _, obj in inspect.getmembers(module, inspect.isclass)
            if issubclass(obj, BaseTask) and obj is not BaseTask and obj.__module__ == spec.name
        }
        if len(classes) != 1:
            problems.append(f"task {task_id}: expected one BaseTask subclass, found {len(classes)}")
            continue
        task_class = next(iter(classes.values()))

        # Every pinned source must be present and byte-identical: a stale asset
        # scores the agent against expectations it was never shown.
        sources = dict(getattr(task_class, "SOURCE_HASHES", None)
                       or getattr(task_class, "_SOURCE_HASHES", None) or {})
        asset_root = target / "cache" / "osworld_v2_assets" / f"task_{task_id}"
        index = {item.name: item for item in asset_root.rglob("*") if item.is_file()}
        for name, expected in sources.items():
            candidate = index.get(Path(name).name)
            if candidate is None:
                problems.append(f"task {task_id}: source asset not installed: {name}")
            elif expected and _sha256(candidate) != str(expected).casefold():
                problems.append(f"task {task_id}: SHA-256 mismatch on {name}")

        upstream = UPSTREAM_ASSETS.get(task_id)
        if upstream and not (target / "cache" / "osworld_v2_assets" / upstream).is_file():
            problems.append(f"task {task_id}: upstream asset missing: {upstream}")

        for relative in EVALUATOR_FIXTURES.get(task_id, []):
            if not (target / relative).is_file():
                problems.append(f"task {task_id}: evaluator input missing: {relative}")

    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--target", type=Path, default=PACKAGE.parent,
                        help="root of the OSWorld-V2 clone (default: parent of this package)")
    parser.add_argument("--tasks", nargs="+", default=None,
                        help="subset of task ids to install (default: every task found "
                             "under tasks/)")
    parser.add_argument("--host-suffix", default=DEFAULT_HOST_SUFFIX,
                        help=f"WEBSITE_HOST_SUFFIX to write into .env (default: {DEFAULT_HOST_SUFFIX})")
    parser.add_argument("--no-patches", action="store_true",
                        help="do not apply patches/*.patch (mocked-website tasks then fail "
                             "setup on a slow HTTPS probe; see README)")
    parser.add_argument("--apply-patches", action="store_true",
                        help=argparse.SUPPRESS)  # accepted for compatibility; patches apply by default
    parser.add_argument("--skip-env", action="store_true",
                        help="do not touch .env")
    parser.add_argument("--no-verify", action="store_true",
                        help="skip the post-install import and asset-digest checks")
    parser.add_argument("--verify-only", action="store_true",
                        help="run the checks against an existing install, copy nothing")
    args = parser.parse_args()

    target = args.target.resolve()
    _log(f"target clone: {target}")
    validate_target(target)
    require_verified_upstream_commit(target)

    available = discover_task_ids()
    _log(f"discovered {len(available)} task(s) under tasks/: {', '.join(available)}")
    if args.tasks:
        unknown = [task_id for task_id in args.tasks if task_id not in available]
        if unknown:
            _fail(f"unknown task id(s): {', '.join(unknown)}. Available: {', '.join(available)}")
        task_ids = args.tasks
    else:
        task_ids = available

    if args.verify_only:
        problems = verify_install(target, task_ids)
        if problems:
            print(f"[install] VERIFY FAILED — {len(problems)} problem(s):", file=sys.stderr)
            for problem in problems:
                print(f"[install]   - {problem}", file=sys.stderr)
            return 1
        _log(f"verified: {len(task_ids)} task(s) import and every source digest matches")
        return 0

    counters = {"written": 0, "overwritten": 0, "unchanged": 0}
    install_tasks(target, task_ids, counters)
    _log("files: {written} new, {overwritten} replaced, {unchanged} already identical".format(**counters))

    if not args.skip_env:
        ensure_env_file(target, args.host_suffix)
    if not args.no_patches:
        patch_problems = apply_patches(target)
        for problem in patch_problems:
            print(f"[install] ERROR: {problem}", file=sys.stderr)
        if patch_problems:
            return 1

    fetch_problems = fetch_upstream_assets(target, task_ids)
    for problem in fetch_problems:
        _log(f"WARNING: {problem}")

    if not args.no_verify:
        problems = verify_install(target, task_ids)
        if problems:
            print(f"[install] VERIFY FAILED — {len(problems)} problem(s):", file=sys.stderr)
            for problem in problems:
                print(f"[install]   - {problem}", file=sys.stderr)
            return 1
        _log(f"verified: {len(task_ids)} task(s) import and every source digest matches")

    asset_base = target / "cache" / "osworld_v2_assets"
    task_list = json.dumps({"tasks": task_ids})
    print()
    _log("install complete. Next:")
    print(f"""
  cd {target}
  export OSWORLD_FILE_BASE_URL={asset_base}

  echo '{task_list}' > /tmp/careerflow_osworld_tasks.json
  uv run python run.py \\
    --provider_name vmware \\
    --path_to_vm ./vmware_vm_data/Ubuntu0/Ubuntu0.vmx \\
    --model <model> \\
    --observation_type screenshot \\
    --test_all_meta_path /tmp/careerflow_osworld_tasks.json \\
    --eval_version v2 \\
    --result_dir ./results/custom_tasks \\
    --max_steps 200 --headless
""")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
