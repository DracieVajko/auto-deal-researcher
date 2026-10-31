"""Remove stale BLE001 noqa comments from narrowed except clauses.

The except clauses in these files were narrowed to specific exception types,
so BLE001 no longer fires and the noqa directives are stale (flagged by RUF100).
The two genuine last-resort handlers (doctor.py, playwright_searcher.py) are
NOT touched - their noqa comments are intentional and stay.
"""

import re
from pathlib import Path

FILES = [
    "src/browser/manager.py",
    "src/llm/client.py",
    "src/searcher/adapters/alza.py",
    "src/searcher/adapters/backmarket.py",
    "src/searcher/adapters/bazos.py",
    "src/searcher/adapters/ebay.py",
    "src/searcher/adapters/facebook.py",
]

PATTERN = re.compile(r"  # noqa: BLE001 -- [^\n]*")

for rel in FILES:
    path = Path(rel)
    text = path.read_text(encoding="utf-8")
    new_text, count = PATTERN.subn("", text)
    if count:
        path.write_text(new_text, encoding="utf-8")
        print(f"{rel}: removed {count} stale noqa directives")
    else:
        print(f"{rel}: no stale noqa found")
