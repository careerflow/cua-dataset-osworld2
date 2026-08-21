# Task-package layout

This repository is intentionally a **setup pack**, not a fork of OSWorld-V2
and not a container for tasks. The consumer supplies the OSWorld-V2 checkout,
Python environment, provider, VM, and model configuration. Tasks are
distributed separately as a zip and extracted into `tasks/`, which this
repository does not track. `install.py` discovers whatever is under `tasks/`
and copies only the files required for each task to the paths OSWorld already
discovers.

## Layout

```text
cua-dataset-osworld2/
  install.py                         # one-command installer and verifier
  shared/                            # helpers copied beside task classes
  patches/                           # narrowly scoped upstream compatibility fixes
  tasks/                             # not tracked here — extract the task zip into it
    task_CF1/
      task_CF1.py                    # one BaseTask subclass
      assets/                        # all task-owned inputs and evaluator fixtures
    task_CF2/
      ...
```

Task ids and count are not fixed. The installer accepts any number of
`tasks/task_<id>/` directories, discovered by pattern at run time.

| Package source | OSWorld-V2 destination |
| --- | --- |
| `tasks/task_<id>/task_<id>.py` | `evaluation_examples/task_class/task_<id>.py` |
| `tasks/task_<id>/assets/**` | `cache/osworld_v2_assets/task_<id>/**` |
| `shared/*.py` | `evaluation_examples/task_class/*.py` |

The task class uses `asset("task_<id>/...")`. With
`OSWORLD_FILE_BASE_URL=<osworld>/cache/osworld_v2_assets`, OSWorld resolves it
to the installed local file. `SetupController.download()` then places only the
files declared by `setup()` in the guest VM.

## Asset visibility boundary

Keep all package-owned artifacts under `assets/`, including agent-visible
inputs and evaluator-only expected data. The **task code** controls which files
cross into the VM. Never include evaluator-only truth files in
`setup_controller.download(...)`; the installer may verify them locally without
leaking them to an agent.

## Adding a task

1. Create `tasks/task_<id>/task_<id>.py` with exactly one `BaseTask` subclass
   whose `id` matches `<id>`.
2. Put every task-owned input, fixture, and gold-standard artifact in
   `tasks/task_<id>/assets/`.
3. Reference local assets through `asset("task_<id>/<relative-path>")`.
4. Pin agent-visible source bytes in `SOURCE_HASHES` (or `_SOURCE_HASHES`).
5. Test clean installation, task import, VM setup, no-op evaluation, and a
   normal end-to-end run before distributing the zip.

Nothing needs to be registered: `install.py` discovers the new directory on
its own. Create a one-task manifest such as `{"tasks":["<id>"]}` and pass it
through `--test_all_meta_path`. The pinned upstream runner then resolves
`evaluation_examples/task_class/task_<id>.py` by filename; no central registry
is needed.
