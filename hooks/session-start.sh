#!/usr/bin/env bash
# SessionStart hook for second-brain plugin
#
# Walks up from $PWD looking for a CLAUDE.md with a <!-- brain --> block.
# If found, injects the effort path and summary into the session context.
# If not found, injects a generic primer so the agent knows the brain exists.

set -euo pipefail

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
            # Extract the brain block (between <!-- brain --> and <!-- /brain -->)
            block=$(sed -n '/^<!-- brain -->/,/^<!-- \/brain -->/p' "$candidate" 2>/dev/null || true)
            if [ -n "$block" ]; then
                effort=$(echo "$block" | grep '^effort:' | head -1 | sed 's/^effort:[[:space:]]*//')
                summary=$(echo "$block" | grep '^summary:' | head -1 | sed 's/^summary:[[:space:]]*//')
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
    context="A second-brain is connected via MCP. No effort is linked to this project yet.\nConsider running brain-context to search for relevant notes and establish the link."
    # Pass the nearest CLAUDE.md path (or PWD) so the agent knows where to write
    if [ -n "$claude_md_path" ]; then
        context="${context}\nNearest CLAUDE.md: ${claude_md_path}"
    else
        context="${context}\nNo CLAUDE.md found. The brain block can be added to a CLAUDE.md in the project root."
    fi
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
