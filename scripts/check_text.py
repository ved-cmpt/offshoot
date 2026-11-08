"""Every tracked or new (not ignored) text file is UTF-8, has LF line endings and holds no U+FFFD replacement character.

    python scripts/check_text.py

A replacement character in a source file means some tool once failed to decode a character and
kept the damage. The Angular compiler copies it into the bundle as it is, so it reaches visitors
(Run 06: the demo banner's em dash). Standard library only; CI runs it on every push.
"""

import subprocess
import sys

BINARY = (".png", ".jpg", ".gif", ".ico", ".woff", ".woff2", ".pdf", ".zip", ".mp4")
REPLACEMENT = chr(0xFFFD)  # Spelled out, so this file passes its own check.


def main() -> int:
    # Tracked files, and new ones not yet added (but never ignored ones such as .env).
    command = ["git", "ls-files", "--cached", "--others", "--exclude-standard"]
    files = subprocess.run(command, capture_output=True, text=True, check=True).stdout.splitlines()
    problems = []
    for path in files:
        if path.lower().endswith(BINARY):
            continue
        raw = open(path, "rb").read()  # noqa: PTH123, SIM115 - short script, plain read.
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            problems.append(f"{path}: not UTF-8 at byte {exc.start}")
            continue
        if REPLACEMENT in text:
            line = text[: text.index(REPLACEMENT)].count("\n") + 1
            problems.append(f"{path}:{line}: U+FFFD replacement character")
        if b"\r" in raw:
            problems.append(f"{path}: CR line endings")
    for problem in problems:
        print(problem)
    print(f"{len(files)} tracked files checked, {len(problems)} problems")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
