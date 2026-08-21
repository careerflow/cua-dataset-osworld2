# cua-dataset-osworld2

Installer for Careerflow benchmark tasks on an **existing OSWorld-V2
installation**. This repository contains no tasks — only the installer,
shared helpers, a compatibility patch, and documentation. Tasks are
distributed separately as a zip file.

## 1. Add the tasks

Extract the Careerflow task zip into `tasks/` at the root of this repository:

```text
cua-dataset-osworld2/
  tasks/
    task_CF1/
      task_CF1.py
      assets/
    task_CF2/
      task_CF2.py
      assets/
    ...
```

Any number of tasks is supported. The installer discovers every
`tasks/task_<id>/task_<id>.py` automatically — nothing needs to be registered
by hand.

## 2. Install

```bash
git clone https://github.com/xlang-ai/OSWorld-V2 OSWorld-V2
git -C OSWorld-V2 checkout 8b6b59660b59832a42a345db8f86fa9f98c37573

(cd OSWorld-V2 && uv run python \
  /path/to/cua-dataset-osworld2/install.py --target "$PWD")
```

The installer copies every discovered task and its assets, adds
`WEBSITE_HOST_SUFFIX` to `.env`, applies the compatibility patch, and verifies
the result. It is idempotent — re-running it also repairs any asset that has
drifted.

Options: `--tasks <id> [<id> ...]` (install a subset) · `--host-suffix <host>`
· `--skip-env` · `--no-patches` · `--no-verify` · `--verify-only`.

## 3. Run

```bash
cd OSWorld-V2
set -a; source .env; set +a
export OSWORLD_FILE_BASE_URL="$PWD/cache/osworld_v2_assets"
uv run python run.py \
  --provider_name vmware \
  --path_to_vm ./vmware_vm_data/Ubuntu0/Ubuntu0.vmx \
  --model <model> \
  --observation_type screenshot \
  --test_all_meta_path /tmp/careerflow_osworld_tasks.json \
  --eval_version v2 \
  --result_dir ./results/custom_tasks \
  --max_steps 200 --headless
```

`install.py` prints the exact task list and command for what it just
installed.

## Documentation

* [docs/TASK_PACKAGE_LAYOUT.md](docs/TASK_PACKAGE_LAYOUT.md) — task and asset layout
* [docs/VM_COMPATIBILITY.md](docs/VM_COMPATIBILITY.md) — VM and hosting requirements
* [task-pack.json](task-pack.json) — machine-readable compatibility contract
