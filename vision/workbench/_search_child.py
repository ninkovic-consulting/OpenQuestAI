"""The regular-expression scan, run as its own short-lived Python process.

Python's `re` cannot be interrupted and holds the interpreter while it
matches, so a pattern that backtracks catastrophically would freeze the
daemon. Running the scan here, under a timeout that kills the process,
keeps the daemon safe. This file imports only the standard library and is
run as a script with `python -I`; it reads a job file the parent wrote and
prints one JSON object.

The parent has already chosen the files (inside the project, not protected,
no links); this process only opens them without following links and scans.
"""

import json
import os
import re
import sys


def main() -> None:
    with open(sys.argv[1], encoding="utf-8") as handle:
        job = json.load(handle)
    flags = re.IGNORECASE if job["ignore_case"] else 0
    pattern = re.compile(job["pattern"], flags)
    root = job["root"]
    max_matches = job["max_matches"]
    max_bytes = job["max_file_bytes"]
    match_chars = job["match_line_chars"]
    shown_chars = job["shown_line_chars"]
    matches = []
    scanned = 0
    binary = 0
    too_big = 0
    more = False
    for rel in job["files"]:
        try:
            fd = os.open(os.path.join(root, rel), os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        except OSError:
            continue
        with os.fdopen(fd, "rb") as handle:
            data = handle.read(max_bytes + 1)
        if len(data) > max_bytes:
            too_big += 1
            continue
        if b"\x00" in data[:8192]:
            binary += 1
            continue
        scanned += 1
        for number, line in enumerate(data.decode("utf-8", errors="replace").splitlines(), 1):
            found = pattern.search(line[:match_chars])
            if found is None:
                continue
            if len(matches) >= max_matches:
                more = True
                break
            text = line
            if len(text) > shown_chars:
                begin = max(found.start() - shown_chars // 3, 0)
                text = ("…" if begin else "") + text[begin : begin + shown_chars] + "…"
            matches.append([rel, number, text])
        if more:
            break
    print(json.dumps({"matches": matches, "scanned": scanned, "binary": binary, "too_big": too_big, "more": more}))


if __name__ == "__main__":
    main()
