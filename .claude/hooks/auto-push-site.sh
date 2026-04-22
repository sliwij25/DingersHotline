#!/bin/bash
# Auto-push picks HTML and site files when modified at end of a Claude session turn.
# Only fires when there are uncommitted changes to site/picks files.

REPO=/Users/joesliwinski/AIProjects/DingersHotline
cd "$REPO" || exit 0

# Check for modified site or picks files
CHANGED=$(git status --porcelain 2>/dev/null | grep -E "(picks/.*\.(html|txt)|docs/index\.html)" | awk '{print $2}')

if [ -z "$CHANGED" ]; then
    exit 0
fi

# Stage and commit changed files
git add picks/*.html picks/*.txt docs/index.html 2>/dev/null
COMMIT_MSG="auto: site update $(date '+%Y-%m-%d %H:%M')"
RESULT=$(git commit -m "$COMMIT_MSG" 2>&1)

if echo "$RESULT" | grep -q "nothing to commit"; then
    exit 0
fi

git push 2>/dev/null
echo "[auto-push] Site changes pushed: $COMMIT_MSG"
