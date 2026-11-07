import subprocess
strategy = "Code health triage 2 complete: 77 review issues triaged across 5 clusters, 13 steps enriched with verified file paths and issue refs, sense-check verified. Execution order: (1) search-types-contracts - normalize conditions, delegate price parsing, annotate currency/accumulators, (2) cli-api-contracts - thread brand filter, phase CLI request object, (3) error-observability - add debug logging to swallowed exceptions, (4) browser-security - make TLS verification opt-in, (5) package-hygiene - declare optional Excel dependency. Verify each cluster with mypy and full pytest suite after fixes."
attestation = "I have completed all 6 triage stages and confirm the plan is ready for execution with all clusters properly organized and enriched"
r = subprocess.run(
    ["python", "-m", "desloppify", "plan", "triage", "--complete", "--strategy", strategy, "--attestation", attestation],
    capture_output=True, text=True, encoding="utf-8", errors="replace",
)
print("stdout:", r.stdout[-300:])
print("stderr:", r.stderr[-300:])
print("returncode:", r.returncode)
