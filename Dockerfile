FROM codercom/code-server:latest

LABEL version="0.3.0"

ARG ZK_VERSION=0.14.1
ARG SQLITE_VEC_VERSION=0.1.6

USER root

# Allow pip to install into the system Python without a venv
ENV PIP_BREAK_SYSTEM_PACKAGES=1

# System tools + Python
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 \
    python3-pip \
    nodejs \
    npm \
    curl \
    fzf \
    ripgrep \
    bat \
    zsh \
    git \
    && rm -rf /var/lib/apt/lists/* \
    && ln -sf /usr/bin/batcat /usr/local/bin/bat

# zk binary
RUN ARCH=$(dpkg --print-architecture) && \
    case "$ARCH" in \
      amd64) ZK_ARCH="linux-amd64" ;; \
      arm64) ZK_ARCH="linux-arm64" ;; \
      *) echo "Unsupported arch: $ARCH" && exit 1 ;; \
    esac && \
    curl -fsSL "https://github.com/zk-org/zk/releases/download/v${ZK_VERSION}/zk-v${ZK_VERSION}-${ZK_ARCH}.tar.gz" \
    | tar xz -C /usr/local/bin/ zk && \
    chmod +x /usr/local/bin/zk

# Python dependencies (excluding sqlite-vec — built from source below)
COPY requirements.txt /tmp/requirements.txt
RUN python3 -m pip install --no-cache-dir \
    $(grep -v sqlite-vec /tmp/requirements.txt | tr '\n' ' ')

# Build sqlite-vec from source (PyPI aarch64 wheel contains a 32-bit binary)
RUN apt-get update && apt-get install -y --no-install-recommends gcc libsqlite3-dev wget \
    && cd /tmp \
    && wget -q "https://github.com/asg017/sqlite-vec/releases/download/v${SQLITE_VEC_VERSION}/sqlite-vec-${SQLITE_VEC_VERSION}-amalgamation.tar.gz" \
    && tar xzf "sqlite-vec-${SQLITE_VEC_VERSION}-amalgamation.tar.gz" \
    && python3 -m pip install --no-cache-dir "sqlite-vec>=${SQLITE_VEC_VERSION}" \
    && SITE_PACKAGES=$(python3 -c "import site; print(site.getsitepackages()[0])") \
    && gcc -shared -fPIC -I/usr/include -o "${SITE_PACKAGES}/sqlite_vec/vec0.so" sqlite-vec.c -lm \
    && apt-get remove -y gcc libsqlite3-dev wget \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/* /tmp/sqlite-vec*

# Claude Code CLI
RUN npm install -g @anthropic-ai/claude-code

# Brain tools
COPY tools/ /usr/local/lib/brain-tools/
COPY zk/ /usr/local/lib/brain-tools/zk/
COPY vscode/ /usr/local/lib/brain-tools/vscode/
RUN chmod +x /usr/local/lib/brain-tools/brain-index \
              /usr/local/lib/brain-tools/brain-search \
              /usr/local/lib/brain-tools/brain-mcp-server \
              /usr/local/lib/brain-tools/brain-api \
              /usr/local/lib/brain-tools/brain-init \
              /usr/local/lib/brain-tools/brain-template-sync \
              /usr/local/lib/brain-tools/entrypoint.sh

# Shell environment for coder user (brain aliases, prompt)
COPY tools/brain.zshrc /home/coder/.zshrc
RUN chown coder:coder /home/coder/.zshrc

# Add brain tools to PATH and Python path (for all users)
ENV PATH="/usr/local/lib/brain-tools:$PATH"
ENV PYTHONPATH="/usr/local/lib/brain-tools"

EXPOSE 7779 8080

# VS Code extensions — must run as coder user
USER coder
RUN code-server --install-extension foam.foam-vscode \
    && code-server --install-extension yzhang.markdown-all-in-one \
    && code-server --install-extension bierner.markdown-preview-github-styles

# Bake in settings and keybindings
COPY --chown=coder:coder code-server/settings.json /home/coder/.local/share/code-server/User/settings.json
COPY --chown=coder:coder code-server/keybindings.json /home/coder/.local/share/code-server/User/keybindings.json

USER root

WORKDIR /brain
ENTRYPOINT ["/usr/local/lib/brain-tools/entrypoint.sh"]
CMD ["--auth", "none", "/brain"]
