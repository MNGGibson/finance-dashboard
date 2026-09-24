#!/bin/bash
# Install a pre-commit hook that refuses a commit containing private words.
# Put one word or phrase per line in .private-words (gitignored): employer, landlord,
# lender, family names, your username, anything that must never reach the public repo.
set -u
cd "$(dirname "$0")/.." || exit 1
cat > .git/hooks/pre-commit <<'HOOK'
#!/bin/bash
# Refuse to commit staged content that contains a word from .private-words.
[ -f .private-words ] || exit 0
staged=$(git diff --cached --name-only --diff-filter=ACM)
[ -n "$staged" ] || exit 0
hits=$(git diff --cached -U0 --diff-filter=ACM | grep '^+' | grep -v '^+++' | grep -n -i -F -f .private-words)
if [ -n "$hits" ]; then
    echo "Commit refused: staged changes contain a private word (see .private-words):" >&2
    echo "$hits" | cut -c1-160 >&2
    echo "Use 'git commit --no-verify' only if this is a false positive." >&2
    exit 1
fi
HOOK
chmod +x .git/hooks/pre-commit
echo "Installed .git/hooks/pre-commit"
[ -f .private-words ] || echo "Create .private-words (one term per line) to activate it."
