#!/bin/bash
# Auto-push picks HTML and site files when modified at end of a Claude session turn.
# Handles two cases: uncommitted changes to site files, or commits not yet pushed.

REPO=/Users/joesliwinski/AIProjects/DingersHotline
cd "$REPO" || exit 0

# Case 1: uncommitted changes to site/picks files — commit then push
CHANGED=$(git status --porcelain 2>/dev/null | grep -E "(picks/.*\.(html|txt)|docs/index\.html|docs/strikeouts\.html|docs/version\.txt)" | awk '{print $2}')

if [ -n "$CHANGED" ]; then
    git add picks/*.html picks/*.txt docs/index.html docs/strikeouts.html docs/version.txt docs/_headers 2>/dev/null
    COMMIT_MSG="auto: site update $(date '+%Y-%m-%d %H:%M')"
    RESULT=$(git commit -m "$COMMIT_MSG" 2>&1)
    if ! echo "$RESULT" | grep -q "nothing to commit"; then
        git push 2>/dev/null
        echo "[auto-push] Site changes committed and pushed: $COMMIT_MSG"
        exit 0
    fi
fi

# Case 2: commits exist that haven't been pushed yet — push them
AHEAD=$(git rev-list --count origin/main..HEAD 2>/dev/null)
if [ "${AHEAD:-0}" -gt 0 ]; then
    git push 2>/dev/null
    echo "[auto-push] Pushed $AHEAD unpushed commit(s) to origin"
fi
