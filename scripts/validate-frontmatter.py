"""Validate YAML frontmatter in docs/solutions/ files for parser-safety issues."""
import re
import sys

def main():
    if len(sys.argv) < 2:
        print("Usage: validate-frontmatter.py <path>", file=sys.stderr)
        sys.exit(1)

    path = sys.argv[1]
    with open(path, encoding="utf-8") as f:
        content = f.read()

    if not content.startswith("---"):
        print(f"ERROR: {path}: missing opening '---' delimiter", file=sys.stderr)
        sys.exit(1)

    parts = content.split("---", 2)
    if len(parts) < 3:
        print(f"ERROR: {path}: missing closing '---' delimiter", file=sys.stderr)
        sys.exit(1)

    frontmatter = parts[1]
    errors = []
    for i, line in enumerate(frontmatter.splitlines(), start=2):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("- "):
            val = stripped[2:]
            if val and not val.startswith('"') and not val.startswith("'"):
                if " #" in val:
                    errors.append(f"line {i}: unquoted ' #' in array item (silent comment truncation): {stripped}")
                if re.search(r"(?<!^)\w: \w", val):
                    pass
        else:
            if ": " in stripped:
                key, _, val = stripped.partition(": ")
                val = val.strip()
                if val and not val.startswith('"') and not val.startswith("'") and not val.startswith("["):
                    if " #" in val:
                        errors.append(f"line {i}: unquoted ' #' in scalar value (silent comment truncation): {stripped}")

    if errors:
        for e in errors:
            print(f"ERROR: {path}: {e}", file=sys.stderr)
        sys.exit(1)

    sys.exit(0)

if __name__ == "__main__":
    main()
