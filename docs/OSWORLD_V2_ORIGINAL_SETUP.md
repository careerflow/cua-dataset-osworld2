# Simplified OSWorld V2 setup

This is a short operational guide for running the **original OSWorld V2
project**. It is intentionally separate from the Careerflow task-pack README.

> Important: for the Careerflow task pack, follow this repository's
> [README](../README.md) instead. It strictly pins a different OSWorld commit
> because the shipped website compatibility patch is tested against that exact
> revision. Do not mix its task pack with the official benchmark release steps
> below.

## 1. Clone a released OSWorld V2 version

Use an official release tag rather than upstream `main` for reproducibility.
The upstream project currently documents `v2026.08.08` as its recommended
release.

```bash
git clone https://github.com/xlang-ai/OSWorld-V2.git
cd OSWorld-V2
git checkout v2026.08.08
```

## 2. Create the Python environment

OSWorld V2 requires Python 3.12 or newer. Install `uv`, then synchronize the
project environment from its lockfile:

```bash
uv sync --frozen
```

Run OSWorld commands through `uv run` so they use this environment.

## 3. Choose the environment provider

Choose the provider that matches where the guest will run. The VM name (for
example, `B1`) is only an identifier; the guest image and provider contract
matter.

| Where OSWorld runs | Usual provider | Notes |
| --- | --- | --- |
| macOS, desktop, bare-metal host | `vmware` | Use VMware Fusion on Apple silicon or VMware Workstation on Windows/Linux. |
| Linux server with KVM | `docker` | Preferred upstream server path. |
| Large-scale official-style evaluation | `aws` | Upstream provides AWS images and documentation. |
| Azure, GCP, other clouds | provider-specific | Code paths exist, but use a migrated V2 image and complete a provider acceptance test first. |

For local VMware, verify that the VM runner sees the guest:

```bash
vmrun -T fusion list       # macOS VMware Fusion
# or: vmrun -T ws list     # VMware Workstation
```

The guest must provide the OSWorld setup service, desktop applications,
screenshot/command/file-transfer support, and a clean snapshot that can be
restored before each task.

## 4. Configure model credentials

Set the model API key in your shell or a local `.env` file. Do not commit it.
When loading a `.env` for direct terminal runs, export its variables:

```bash
set -a; source .env; set +a
```

Some official tasks also need a mocked-website suffix or a private GitLab
deployment. Follow the upstream provider and release documentation before
enabling those task families.

## 5. Download official V2 tasks and assets

First accept access to the gated Hugging Face task and asset datasets, then log
in locally:

```bash
uvx --from huggingface_hub hf auth login
```

Download task classes and the matching local asset snapshot:

```bash
uv run scripts/tools/download_osworld_v2_tasks.py \
  --benchmark-release osworld-v2-2026.08.08

uv run scripts/tools/download_osworld_v2_assets.py \
  --benchmark-release osworld-v2-2026.08.08 \
  --target-dir cache/osworld_v2_assets \
  --clean

export OSWORLD_FILE_BASE_URL="$PWD/cache/osworld_v2_assets"
```

Keep code, task classes, assets, websites, and provider images on the same
benchmark release. Do not substitute `main` for a release tag in a comparable
evaluation.

## 6. Run one official V2 task

Create a one-task manifest and point the runner to the appropriate provider.

```bash
echo '{"tasks":["001"]}' > /tmp/osworld-one-task.json

uv run python run.py \
  --provider_name vmware \
  --path_to_vm /absolute/path/to/Ubuntu0.vmx \
  --model gpt-4o \
  --observation_type screenshot \
  --test_all_meta_path /tmp/osworld-one-task.json \
  --eval_version v2 \
  --result_dir ./results/official-v2 \
  --max_steps 15 \
  --headless
```

For AWS, Docker, Azure, or GCP, replace the provider and VM target with that
provider's OSWorld configuration; do not reuse the VMware `.vmx` argument.

## 7. Before trusting a new environment

Run one small task and confirm all of the following:

1. The provider restores the expected clean snapshot.
2. The host reaches the guest setup service.
3. A local asset is transferred into the guest.
4. A screenshot and trajectory are written to the result directory.
5. The evaluator writes `result.json`.

Only after this smoke run should the environment be used for batch evaluation.

## Upstream references

- [OSWorld V2 README](https://github.com/xlang-ai/OSWorld-V2/blob/main/README.md)
- [OSWorld V2 provider setup](https://github.com/xlang-ai/OSWorld-V2/blob/main/docs/PROVIDER_SETUP.md)
- [OSWorld V2 benchmark releases](https://github.com/xlang-ai/OSWorld-V2/tree/main/benchmark_releases)
