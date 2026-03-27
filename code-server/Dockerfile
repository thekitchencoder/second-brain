FROM codercom/code-server:latest

USER root

# Install Node.js and npm, then Claude Code CLI
RUN apt-get update && apt-get install -y --no-install-recommends nodejs npm \
    && rm -rf /var/lib/apt/lists/* \
    && npm install -g @anthropic-ai/claude-code

USER coder

# Pre-install VS Code extensions
RUN code-server --install-extension foam.foam-vscode \
    && code-server --install-extension yzhang.markdown-all-in-one \
    && code-server --install-extension bierner.markdown-preview-github-styles

# Bake in settings and keybindings
COPY --chown=coder:coder settings.json /home/coder/.local/share/code-server/User/settings.json
COPY --chown=coder:coder keybindings.json /home/coder/.local/share/code-server/User/keybindings.json

# Vault is mounted at /brain — open it as the default workspace
WORKDIR /brain
