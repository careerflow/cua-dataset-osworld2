# VM compatibility

Careerflow tasks are portable across **host locations**, not arbitrary guest
images. You may run the supported OSWorld Ubuntu guest locally with VMware,
or host an equivalent guest with a supported cloud provider such as AWS, Azure,
or GCP. The task package does not depend on the host's physical location.

The guest must still satisfy OSWorld's runtime contract:

1. It is the compatible Ubuntu snapshot for the task (`ubuntu` for CF7).
2. The chosen OSWorld provider can start/revert the VM and reach its setup API.
3. It supports screenshot capture, command execution, and host-to-guest file
   transfer.
4. It includes the applications named by the task. CF7 requires the file
   manager, PDF viewer, terminal, calculator, and text editor.
5. It has a clean snapshot that the provider can restore before each run.

CF10 additionally requires WPS Presentation (`wpp`) because it creates and
scores native WPS animation data. The stock OSWorld image is not guaranteed to
include it; verify `command -v wpp` inside the guest before claiming CF10 is
ready. A VM with only LibreOffice Impress is not equivalent for CF10.

For the verified local configuration, CF7 uses VMware Fusion with:

```text
Provider: vmware
Guest:    Ubuntu0
Snapshot: init_state
VMX:      /absolute/path/to/Ubuntu0.vmx
```

The guest environment was live-tested with CF7 setup: OSWorld reverted to
`init_state`, connected to the setup service, transferred the entire filing
packet, created the four Desktop deliverables, and opened the packet. A model
trajectory was then started and the VM restored to `init_state` after the
smoke run. This confirms the task-loading path, not that every model will
solve the task.

For a cloud deployment, replace `--provider_name vmware` and `--path_to_vm`
with the provider's OSWorld configuration. Do not point CF7 at a generic
desktop VM that lacks the OSWorld setup service or the required snapshot: the
task's asset loading and evaluation cannot be guaranteed there.
