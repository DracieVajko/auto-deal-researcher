import subprocess
for step in [1, 2, 3, 4]:
    r = subprocess.run(
        ["python", "-m", "desloppify", "plan", "cluster", "update", "cli-api-contracts", "--done-step", str(step)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    print(f"Step {step}: {r.returncode}")
