"""
Creates Windows Task Scheduler tasks for the UBW Instagram automation.

Registers 7 tasks:
  UBW_Instagram_Slot1  → 10:00 AM  Mon–Sat
  UBW_Instagram_Slot2  → 11:30 AM  Mon–Sat
  UBW_Instagram_Slot3  → 01:00 PM  Mon–Sat
  UBW_Instagram_Slot4  → 02:30 PM  Mon–Sat
  UBW_Instagram_Slot5  → 06:00 PM  Mon–Sat
  UBW_Instagram_Slot6  → 07:30 PM  Mon–Sat
  UBW_Instagram_Summary→ 08:00 PM  Mon–Sat

Usage:
    python tools/setup_scheduler.py          # create / update all tasks
    python tools/setup_scheduler.py --list   # show registered UBW tasks
    python tools/setup_scheduler.py --delete # remove all UBW tasks
"""

import argparse
import subprocess
import sys
from pathlib import Path

PYTHON      = sys.executable
TOOLS_DIR   = Path(__file__).parent
WORK_DIR    = TOOLS_DIR.parent

SLOT_TIMES  = ["10:00", "11:30", "13:00", "14:30", "18:00", "19:30"]
SUMMARY_TIME = "20:00"
DAYS        = "Monday,Tuesday,Wednesday,Thursday,Friday,Saturday"


def _run_ps(script: str):
    result = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"PowerShell error:\n{result.stderr.strip()}")
    return result.stdout.strip()


def create_tasks():
    tasks = []

    for slot, time_str in enumerate(SLOT_TIMES, start=1):
        tasks.append({
            "name": f"UBW_Instagram_Slot{slot}",
            "script": str(TOOLS_DIR / "run_daily_posts.py"),
            "args": f"--slot {slot}",
            "time": time_str,
        })

    tasks.append({
        "name": "UBW_Instagram_Summary",
        "script": str(TOOLS_DIR / "send_daily_summary.py"),
        "args": "",
        "time": SUMMARY_TIME,
    })

    for task in tasks:
        args_str = f" {task['args']}" if task["args"] else ""
        ps = f"""
$action  = New-ScheduledTaskAction `
    -Execute '{PYTHON}' `
    -Argument '"{task["script"]}"{args_str}' `
    -WorkingDirectory '{WORK_DIR}'

$trigger = New-ScheduledTaskTrigger `
    -Weekly `
    -DaysOfWeek {DAYS} `
    -At '{task["time"]}'

$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 10)

Register-ScheduledTask `
    -TaskName '{task["name"]}' `
    -Action   $action `
    -Trigger  $trigger `
    -Settings $settings `
    -Force | Out-Null

Write-Host 'Created: {task["name"]} at {task["time"]}'
"""
        print(_run_ps(ps))

    print(f"\nAll {len(tasks)} tasks registered. Run --list to verify.")


def list_tasks():
    output = _run_ps(
        "Get-ScheduledTask | Where-Object { $_.TaskName -like 'UBW_*' } | "
        "Select-Object TaskName, State | Format-Table -AutoSize"
    )
    print(output if output else "No UBW tasks found.")


def delete_tasks():
    ps = """
$tasks = Get-ScheduledTask | Where-Object { $_.TaskName -like 'UBW_*' }
foreach ($t in $tasks) {
    Unregister-ScheduledTask -TaskName $t.TaskName -Confirm:$false
    Write-Host "Deleted: $($t.TaskName)"
}
"""
    print(_run_ps(ps))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--list",   action="store_true", help="List registered UBW tasks")
    parser.add_argument("--delete", action="store_true", help="Delete all UBW tasks")
    args = parser.parse_args()

    if args.list:
        list_tasks()
    elif args.delete:
        delete_tasks()
    else:
        create_tasks()
