#!/usr/bin/env bash
# Install local commit-msg hook to enforce TIP / chore / docs / fix / feat prefix.
# Run once per clone:  bash scripts/install-commit-hook.sh

set -euo pipefail

HOOK_PATH=".git/hooks/commit-msg"

cat > "$HOOK_PATH" <<'EOF'
#!/usr/bin/env bash
# DermAssist VN commit-msg hook
# Enforce: first line starts with TIP-XXX:, TIP-XXX-V1:, chore:, docs:, fix:, feat:, or test:
# Allow: merge commits, fixup commits.

msg_file="$1"
first_line=$(head -n1 "$msg_file")

# Skip merge commits and fixup commits
if [[ "$first_line" == Merge* ]] || [[ "$first_line" == fixup!* ]] || [[ "$first_line" == squash!* ]]; then
    exit 0
fi

# Allowed prefixes
if [[ "$first_line" =~ ^(TIP-[A-Z0-9-]+|chore|docs|fix|feat|test|refactor|build|ci): ]]; then
    exit 0
fi

echo "Commit message must start with one of:"
echo "    TIP-XXX:        (canonical TIP work, e.g. 'TIP-008-V1: ...')"
echo "    chore:          (dependencies, build, housekeeping)"
echo "    docs:           (documentation only)"
echo "    fix:            (bugfix outside TIP boundary)"
echo "    feat:           (small feature outside TIP)"
echo "    test:           (test-only change)"
echo "    refactor:       (code shape, no behavior change)"
echo ""
echo "Got: '$first_line'"
echo ""
echo "If this is a TIP, prefix with the TIP-ID (e.g. 'TIP-008-V1: ...')."
exit 1
EOF

chmod +x "$HOOK_PATH"
echo "commit-msg hook installed at $HOOK_PATH"
