"""Cross-platform task scheduler for automated runs."""

import os
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
            subprocess.run(["powershell", "-Command", ps_cmd], check=True, timeout=30)
            print(f"Installed Windows task: {safe_name}")


def _uninstall_windows_tasks():
    subprocess.run([
        "powershell", "-Command",
        "Get-ScheduledTask -TaskName 'AutoDealSearcher-*' | Unregister-ScheduledTask -Confirm:$false"
    ], check=False, timeout=30)
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
        current = subprocess.run(
            ["crontab", "-l"], capture_output=True, text=True, check=True, timeout=10
        ).stdout
    except subprocess.CalledProcessError:
        current = ""

    new_cron = current.rstrip() + "\n" + "\n".join(cron_lines) + "\n"
    subprocess.run(["crontab", "-"], input=new_cron, text=True, check=True, timeout=10)
    print("Installed cron jobs")


def _uninstall_unix_cron():
    try:
        current = subprocess.run(
            ["crontab", "-l"], capture_output=True, text=True, check=True, timeout=10
        ).stdout
    except subprocess.CalledProcessError:
        current = ""

    lines = [line for line in current.splitlines() if "src.cli run" not in line]
    subprocess.run(["crontab", "-"], input="\n".join(lines) + "\n", text=True, check=True, timeout=10)
    print("Removed cron jobs")


def install_startup(daily_at: str = "05:00"):
    """Register the daily monitor run at *daily_at* (default 05:00).

    The service drains every due job and exits when the queue is empty, so
    this is a daily batch run rather than a permanent daemon.  The action is
    launched through ``pythonw.exe`` when available (no console window /
    no popup), falling back to PowerShell with ``-WindowStyle Hidden``.
    """
    if sys.platform != "win32":
        return
    python_exe = sys.executable
    repo_root = str(Path.cwd())
    safe_name = "AutoDealSearcher-Monitor"

    def _ps_quote(value: str) -> str:
        return "'" + str(value).replace("'", "''") + "'"

    quoted_name = _ps_quote(safe_name)
    quoted_dir = _ps_quote(repo_root)
    quoted_args = _ps_quote("-m src.cli schedule service --exit-when-idle")
    quoted_time = _ps_quote(daily_at)

    # Prefer pythonw.exe (Windows GUI build of Python, no console window).
    pythonw_exe = os.path.join(os.path.dirname(python_exe), "pythonw.exe")
    if os.path.exists(pythonw_exe):
        quoted_exe = _ps_quote(pythonw_exe)
        ps_cmd = f"""
$action = New-ScheduledTaskAction -Execute {quoted_exe} -Argument {quoted_args} -WorkingDirectory {quoted_dir}
$trigger = New-ScheduledTaskTrigger -Daily -At {quoted_time}
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -DontStopOnIdleEnd -AllowStartIfOnBatteries -Hidden
Register-ScheduledTask -TaskName {quoted_name} -Action $action -Trigger $trigger -Settings $settings -Force
"""
    else:
        # Fallback: hide the console window via PowerShell.
        quoted_exe = _ps_quote(python_exe)
        ps_cmd = f"""
$action = New-ScheduledTaskAction -Execute powershell.exe -Argument '-NoProfile -WindowStyle Hidden -Command & {{ & {quoted_exe} {quoted_args} }}' -WorkingDirectory {quoted_dir}
$trigger = New-ScheduledTaskTrigger -Daily -At {quoted_time}
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -DontStopOnIdleEnd -AllowStartIfOnBatteries -Hidden
Register-ScheduledTask -TaskName {quoted_name} -Action $action -Trigger $trigger -Settings $settings -Force
"""
    # Register via PowerShell. `powershell.exe` is a trusted system binary and
    # the command string is fully internal (no user input), so this is safe.
    subprocess.run(["powershell.exe", "-Command", ps_cmd], check=True, timeout=30)  # noqa: S603, S607 - intentional system Task Scheduler install
    print(f"Installed Windows startup task: {safe_name}")


def uninstall_startup():
    """Remove the Windows logon startup task for the monitor."""
    if sys.platform != "win32":
        return
    # Unregister the startup task. Trusted system binary, internal command.
    subprocess.run([  # noqa: S607 - intentional system Task Scheduler uninstall
        "powershell.exe", "-Command",
        "Get-ScheduledTask -TaskName 'AutoDealSearcher-Monitor' -ErrorAction SilentlyContinue | Unregister-ScheduledTask -Confirm:$false"
    ], check=False, timeout=30)
    print("Removed Windows startup task")
