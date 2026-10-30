"""Cross-platform task scheduler for automated runs."""

import shlex
import subprocess
import sys
from pathlib import Path

from src.config.models import AppConfig


def install_schedule(config: AppConfig):
    """Install scheduled tasks for all enabled schedule.tasks entries."""
    if sys.platform == "win32":
        _install_windows_tasks(config)
    else:
        _install_unix_cron(config)


def uninstall_schedule():
    """Remove scheduled tasks."""
    if sys.platform == "win32":
        _uninstall_windows_tasks()
    else:
        _uninstall_unix_cron()


def _install_windows_tasks(config: AppConfig):
    python_exe = sys.executable
    for task in config.schedule.tasks:
        if not task.enabled:
            continue
        for time_str in task.times:
            safe_name = "".join(c for c in f"AutoDealSearcher-{task.name}-{time_str.replace(':', '')}" if c.isalnum() or c in "-_")
            # PowerShell single-quoted literals; escape embedded single quotes by doubling.
            def _ps_quote(value: str) -> str:
                return "'" + str(value).replace("'", "''") + "'"
            quoted_exe = _ps_quote(python_exe)
            quoted_prompt = _ps_quote(task.prompt_file)
            quoted_time = _ps_quote(time_str)
            quoted_name = _ps_quote(safe_name)
            # PowerShell command to create scheduled task
            ps_cmd = f'''
$action = New-ScheduledTaskAction -Execute {quoted_exe} -Argument '-m src.cli run --prompt-file {quoted_prompt}'
$trigger = New-ScheduledTaskTrigger -Daily -At {quoted_time}
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -DontStopOnIdleEnd
Register-ScheduledTask -TaskName {quoted_name} -Action $action -Trigger $trigger -Settings $settings -Force
'''
            subprocess.run(["powershell", "-Command", ps_cmd], check=True)
            print(f"Installed Windows task: {safe_name}")


def _uninstall_windows_tasks():
    subprocess.run([
        "powershell", "-Command",
        "Get-ScheduledTask -TaskName 'AutoDealSearcher-*' | Unregister-ScheduledTask -Confirm:$false"
    ], check=False)
    print("Removed Windows tasks")


def _install_unix_cron(config: AppConfig):
    python_exe = sys.executable
    repo_root = Path.cwd()

    cron_lines = []
    for task in config.schedule.tasks:
        if not task.enabled:
            continue
        for time_str in task.times:
            hour, minute = time_str.split(":")
            quoted_root = shlex.quote(str(repo_root))
            quoted_exe = shlex.quote(python_exe)
            quoted_prompt = shlex.quote(task.prompt_file)
            cron_lines.append(
                f"{minute} {hour} * * * cd {quoted_root} && {quoted_exe} -m src.cli run --prompt-file {quoted_prompt}"
            )

    # Add to crontab
    try:
        current = subprocess.run(["crontab", "-l"], capture_output=True, text=True, check=True).stdout
    except subprocess.CalledProcessError:
        current = ""

    new_cron = current.rstrip() + "\n" + "\n".join(cron_lines) + "\n"
    subprocess.run(["crontab", "-"], input=new_cron, text=True, check=True)
    print("Installed cron jobs")


def _uninstall_unix_cron():
    try:
        current = subprocess.run(["crontab", "-l"], capture_output=True, text=True, check=True).stdout
    except subprocess.CalledProcessError:
        current = ""

    lines = [line for line in current.splitlines() if "src.cli run" not in line]
    subprocess.run(["crontab", "-"], input="\n".join(lines) + "\n", text=True, check=True)
    print("Removed cron jobs")