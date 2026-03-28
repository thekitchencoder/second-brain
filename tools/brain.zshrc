# Brain shell environment

# History — persist across sessions via the zsh-data volume
setopt INC_APPEND_HISTORY   # write each command immediately, not on shell exit
setopt HIST_IGNORE_DUPS     # skip duplicate consecutive entries

# Prompt — makes it clear where you are
PROMPT='%F{green}[brain]%f %F{yellow}%~%f %# '

# Browse all notes with bat preview
alias preview="zk list --quiet --format '{{absPath}}' | fzf --preview 'bat --color=always {}'"

# Quick filters
alias recent="zk list --sort created- --limit 10"
alias drafts="zk list --match 'status:draft'"

# Semantic search shorthand
alias search="brain-search"

# Reindex manually (watcher runs automatically in background)
alias reindex="brain-index run"

# Watcher log
alias watchlog="tail -f /brain/.ai/watch.log"
