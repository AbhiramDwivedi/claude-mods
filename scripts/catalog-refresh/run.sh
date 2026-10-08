#!/usr/bin/env bash
# Weekly refresh of the workflow-audit catalog, run by a scheduler.
# Headless Claude edits only the catalog; this script does the git and PR work.
# Stdout is the message the scheduler delivers, so keep it to a line or two.
set -uo pipefail

REPO=${REPO:-$HOME/Projects/claude-ops}
CLAUDE=${CLAUDE:-$HOME/.local/share/mise/shims/claude}
GH=${GH:-$HOME/.local/share/mise/shims/gh}
BUDGET_USD=${BUDGET_USD:-5}
BASE=${BASE:-main}
TODAY=$(date +%F)
# Two weeks, so one missed run (laptop asleep) leaves no gap.
SINCE=$(date -d "14 days ago" +%F)
BRANCH=catalog-refresh/$(date +%F-%H%M)
LOG_DIR=$HOME/.local/state/catalog-refresh
LOG=$LOG_DIR/$TODAY.log
WT=$(mktemp -d)/wt
mkdir -p "$LOG_DIR"

fail() { echo "Catalog refresh FAILED: $1 (log: $LOG on omarchy)"; exit 1; }
PUSHED=0
cleanup() {
  git -C "$REPO" worktree remove --force "$WT" >>"$LOG" 2>&1
  rmdir "$(dirname "$WT")" 2>>"$LOG"
  [ "$PUSHED" = 1 ] || git -C "$REPO" branch -q -D "$BRANCH" >>"$LOG" 2>&1
}
trap cleanup EXIT

{ echo "=== $(date -Is) start"; } >>"$LOG"

# A refresh PR still open means the last run's changes aren't in main yet; a new run would redo them.
open_pr=$(cd "$REPO" && "$GH" pr list --state open --json number,headRefName,url \
  --jq '[.[] | select(.headRefName | startswith("catalog-refresh/"))][0].url // empty' 2>>"$LOG") \
  || fail "gh pr list"
if [ -n "$open_pr" ]; then
  echo "Catalog refresh skipped: last week's PR is still open, merge or close it first: $open_pr"
  exit 0
fi

git -C "$REPO" fetch -q origin "$BASE" >>"$LOG" 2>&1 || fail "git fetch"
git -C "$REPO" worktree add -q -b "$BRANCH" "$WT" "origin/$BASE" >>"$LOG" 2>&1 || fail "git worktree add"
cd "$WT" || fail "cd worktree"

prompt=$(sed -e "s/{{TODAY}}/$TODAY/g" -e "s/{{SINCE}}/$SINCE/g" scripts/catalog-refresh/prompt.md 2>>"$LOG")
[ -n "$prompt" ] || fail "no prompt.md on origin/$BASE"
out=$(timeout 45m "$CLAUDE" -p "$prompt" \
  --model sonnet \
  --permission-mode dontAsk \
  --allowedTools WebFetch WebSearch Read Grep Glob \
    "Edit(plugins/workflow-audit/catalog/**)" \
    "Bash(python -m unittest discover -s plugins/workflow-audit/tests)" \
  --max-budget-usd "$BUDGET_USD" \
  --no-session-persistence \
  --output-format json 2>>"$LOG")
rc=$?
echo "$out" >>"$LOG"
[ $rc -eq 0 ] || fail "claude exited $rc"

body=$(jq -r '.result // empty' <<<"$out")
[ -n "$body" ] || fail "claude returned no result"
summary=$(grep -m1 '^SUMMARY:' <<<"$body" | sed 's/^SUMMARY: *//')
summary=${summary:-catalog changes}

changed=$(git status --porcelain)
if [ -z "$changed" ]; then
  echo "Catalog refresh: no changes. $summary"
  exit 0
fi
# The allowlist should already prevent this; check anyway before anything leaves the machine.
if grep -v ' plugins/workflow-audit/catalog/' <<<"$changed" | grep -q .; then
  fail "edits outside the catalog: $(tr '\n' ' ' <<<"$changed")"
fi
python3 -m unittest discover -s plugins/workflow-audit/tests >>"$LOG" 2>&1 || fail "catalog tests fail"

# Users on marketplace auto-update only get the new catalog if the plugin version moves.
python3 - <<'EOF' || fail "version bump"
import json, pathlib
p = pathlib.Path("plugins/workflow-audit/.claude-plugin/plugin.json")
d = json.loads(p.read_text())
major, minor, patch = d["version"].split(".")
d["version"] = f"{major}.{minor}.{int(patch) + 1}"
p.write_text(json.dumps(d, indent=2, ensure_ascii=False) + "\n")
EOF

git add -A
git -c user.name="Ram Dwivedi" -c user.email="abhiram.dwivedi@yahoo.com" commit -q \
  -m "Catalog refresh $TODAY: $summary" \
  -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>" >>"$LOG" 2>&1 || fail "git commit"
git -c credential.helper= -c credential.helper="!$GH auth git-credential" \
  push -q -u origin "$BRANCH" >>"$LOG" 2>&1 || fail "git push"
PUSHED=1

pr_body="$(grep -v '^SUMMARY:' <<<"$body")

Opened by the weekly catalog refresh (scripts/catalog-refresh). Check the sources before merging.

🤖 Generated with [Claude Code](https://claude.com/claude-code)"
pr_url=$("$GH" pr create --base "$BASE" --head "$BRANCH" \
  --title "Catalog refresh $TODAY: $summary" --body "$pr_body" 2>>"$LOG") || fail "gh pr create"

echo "Catalog refresh: $summary"
echo "$pr_url"
