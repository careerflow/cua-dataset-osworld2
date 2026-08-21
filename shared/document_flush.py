"""Flush unsaved office documents before a final evaluation.

Original OSWorld tasks (004, 015, …) do not make "did the agent remember to
press Ctrl+S" part of the measurement: their evaluators activate the document
window and send Ctrl+S themselves before reading the file. This module provides
the same guarantee for the custom tasks, with two differences that matter here:

* it is only ever applied to a **final** evaluation.  The tasks that use it
  declare ``intermediate_eval_safe = False`` so the runner scores them exactly
  once, at the end; a forced save at a checkpoint would mutate the agent's own
  workspace mid-trajectory;
* it saves every open LibreOffice document rather than one named window, so a
  task with a workbook, a text document and a deck needs no window bookkeeping.

The helper is a no-op unless the caller has marked the environment as final, so
unit tests and read-only probes are unaffected.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Sequence

logger = logging.getLogger("desktopenv.document_flush")

# Activate the deliverable's window with wmctrl, then drive the save with
# pyautogui exactly as original OSWorld tasks 004/015 do. The benchmark image
# ships wmctrl and pyautogui but NOT xdotool, so xdotool must not be relied on.
#
# Only windows whose title matches a declared deliverable are saved. Saving
# every open LibreOffice window also rewrites read-only source documents the
# agent merely opened to read, which changes their bytes and trips the task's
# own source-integrity cap: a run then loses 0.40 for a mutation the evaluator
# itself caused.
_FLUSH_TEMPLATE = r"""
command -v wmctrl >/dev/null || { echo "flushed=0"; exit 0; }
saved=0
for id in $(wmctrl -l | grep -E 'LibreOffice (Calc|Writer|Impress|Draw)' | grep -E '__PATTERN__' | awk '{print $1}'); do
  wmctrl -i -a "$id" || continue
  sleep 0.8
  DISPLAY=:0 python3 -c "import pyautogui, time; pyautogui.hotkey('ctrl','s'); time.sleep(1.8); pyautogui.press('enter'); time.sleep(1.2)" || continue
  saved=$((saved+1))
done
echo "flushed=$saved"
"""


def is_final_evaluation(env: Any) -> bool:
    """True unless the runner has explicitly marked this call as a checkpoint.

    Portable build: upstream OSWorld never sets ``final_evaluation``, so a
    default of ``False`` would silently disable the flush and score unsaved
    LibreOffice work as missing. The four tasks that use this helper declare
    ``intermediate_eval_safe = False``, so the runner only ever calls
    ``evaluate()`` once, at the end — defaulting to True is therefore safe and
    needs no runner patch. A runner that does set the flag still wins.
    """
    return bool(getattr(env, "final_evaluation", True))


def flush_open_documents(env: Any, deliverables: Sequence[str] = (), *,
                         settle_seconds: float = 2.0) -> dict[str, Any]:
    """Save the task's own deliverables; no-op outside a final evaluation.

    ``deliverables`` are output file names, e.g. ``("Q4_AP_Close_Workbook.xlsx",)``.
    Nothing else is touched, so supplied sources stay byte-identical.
    """
    if not is_final_evaluation(env):
        return {"attempted": False, "reason": "not a final evaluation"}
    if not deliverables:
        return {"attempted": False, "reason": "no deliverables declared"}
    # Imported lazily: task test harnesses stub ``desktop_env`` with only the
    # getters they need, and a flush is never exercised in those paths.
    from desktop_env.evaluators.getters import get_vm_command_line

    try:
        pattern = "|".join(re.escape(name) for name in deliverables)
        command = _FLUSH_TEMPLATE.replace("__PATTERN__", pattern)
        output = str(get_vm_command_line(env, {
            "command": ["bash", "-lc", command], "timeout": 90, "silent": True,
        }) or "")
        flushed = 0
        for line in output.splitlines():
            if line.strip().startswith("flushed="):
                flushed = int(line.strip().split("=", 1)[1] or 0)
        if flushed and settle_seconds:
            get_vm_command_line(env, {
                "command": ["bash", "-lc", f"sleep {settle_seconds}"],
                "timeout": 30, "silent": True,
            })
        logger.info("Final evaluation flushed %s deliverable document(s).", flushed)
        return {"attempted": True, "documents_saved": flushed, "deliverables": list(deliverables)}
    except Exception as error:  # a flush failure must never mask the real score
        logger.warning("Document flush failed: %s", error)
        return {"attempted": True, "error": f"{type(error).__name__}: {error}"}
