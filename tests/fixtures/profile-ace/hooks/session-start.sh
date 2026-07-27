#!/usr/bin/env bash
# SessionStart hook for second-brain plugin
#
# Walks up from $PWD looking for a CLAUDE.md with a <!-- brain --> block.
# If found, injects the effort path and summary into the session context.
# If not found, stays silent (empty additionalContext) so unrelated projects
# and other installed profiles are unaffected.

set -euo pipefail

# The engine stages the effective marker (possibly brain-name-qualified) at
# hooks/marker; fall back to the unqualified default when absent.
HOOK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MARKER="brain"
if [ -f "$HOOK_DIR/marker" ]; then
    MARKER="$(cat "$HOOK_DIR/marker")"
fi

# --- Find the brain block in the nearest CLAUDE.md ---

effort=""
summary=""
claude_md_path=""

nearest_claude_md=""

dir="$PWD"
while [ "$dir" != "/" ]; do
    for candidate in "$dir/CLAUDE.md" "$dir/.claude/CLAUDE.md"; do
        if [ -f "$candidate" ]; then
            # Track the nearest CLAUDE.md for writeback even if it has no brain block
            if [ -z "$nearest_claude_md" ]; then
                nearest_claude_md="$candidate"
            fi
            # Extract the brain block (between <!-- $MARKER --> and <!-- /$MARKER -->)
            block=$(sed -n "/^<!-- ${MARKER} -->/,/^<!-- \/${MARKER} -->/p" "$candidate" 2>/dev/null || true)
            if [ -n "$block" ]; then
                # || true: a block missing either line must not kill the hook
                # under pipefail — SessionStart must stay silent, not fail.
                effort=$(echo "$block" | { grep '^effort:' || true; } | head -1 | sed 's/^effort:[[:space:]]*//')
                summary=$(echo "$block" | { grep '^summary:' || true; } | head -1 | sed 's/^summary:[[:space:]]*//')
                claude_md_path="$candidate"
                break 2
            fi
        fi
    done
    dir=$(dirname "$dir")
done

# If we found a brain block, claude_md_path is set. Otherwise fall back to nearest.
if [ -z "$claude_md_path" ]; then
    claude_md_path="$nearest_claude_md"
fi

# --- Escape for JSON ---

escape_for_json() {
    local input="$1"
    local output=""
    local i char
    for (( i=0; i<${#input}; i++ )); do
        char="${input:$i:1}"
        case "$char" in
            $'\\') output+='\\' ;;
            '"') output+='\"' ;;
            $'\n') output+='\n' ;;
            $'\r') output+='\r' ;;
            $'\t') output+='\t' ;;
            *) output+="$char" ;;
        esac
    done
    printf '%s' "$output"
}

# --- Build context ---

if [ -n "$effort" ]; then
    context="This project is linked to a brain effort: ${effort}"
    if [ -n "$summary" ]; then
        context="${context}\nSummary: ${summary}"
    fi
    context="${context}\n\nThe brain-context skill can load full project context (effort notes, context primers, related work) from the brain. Use it when the conversation would benefit from prior knowledge."
    if [ -n "$claude_md_path" ]; then
        context="${context}\nCLAUDE.md with brain block: ${claude_md_path}"
    fi
else
    # No brain-marked project here — stay silent so unrelated projects and
    # other installed brains are unaffected.
    context=""
fi

escaped_context=$(escape_for_json "$context")

# --- Output JSON ---

cat <<EOF
{
  "hookSpecificOutput": {
    "hookEventName": "SessionStart",
    "additionalContext": "${escaped_context}"
  }
}
EOF

exit 0
