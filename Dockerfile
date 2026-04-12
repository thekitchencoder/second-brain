FROM debian:bookworm-slim

LABEL version="1.0.2"

ARG ZK_VERSION=0.14.1
ARG SQLITE_VEC_VERSION=0.1.6

# Create coder user (codercom/code-server provided this; we now create it explicitly)
RUN groupadd --gid 1000 coder \
    && useradd --uid 1000 --gid coder --shell /bin/zsh --create-home coder

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
              /usr/local/lib/brain-tools/entrypoint.sh \
              /usr/local/lib/brain-tools/entrypoint-ui.sh \
              /usr/local/lib/brain-tools/setup.sh

# Shell environment — copy to both coder and root (container runs as root)
COPY tools/brain.zshrc /home/coder/.zshrc
COPY tools/brain.zshrc /root/.zshrc
RUN chown coder:coder /home/coder/.zshrc

# System-wide zsh environment — ensures brain tools are on PATH for all zsh
# instances (login, non-login, interactive, non-interactive) regardless of user
RUN echo 'export PATH="/usr/local/lib/brain-tools:$PATH"' > /etc/zsh/zshenv \
    && echo 'export PYTHONPATH="/usr/local/lib/brain-tools"' >> /etc/zsh/zshenv \
    && echo 'export HISTFILE="/home/coder/.zsh-data/history"' >> /etc/zsh/zshenv \
    && echo 'export HISTSIZE=10000' >> /etc/zsh/zshenv \
    && echo 'export SAVEHIST=10000' >> /etc/zsh/zshenv

# Add brain tools to PATH and Python path (for non-zsh processes)
ENV PATH="/usr/local/lib/brain-tools:$PATH"
ENV PYTHONPATH="/usr/local/lib/brain-tools"
ENV HISTFILE="/home/coder/.zsh-data/history"

EXPOSE 7779 7780

# Seed files for Claude Code user config — copied idempotently at startup
# so settings survive rebuilds once edited. See tools/entrypoint.sh.
COPY --chown=coder:coder claude/seed/ /usr/local/lib/brain-tools/claude-seed/
COPY --chown=coder:coder claude/plugin-claude.md claude/vault-claude.md /usr/local/lib/brain-tools/claude/
COPY --chown=coder:coder skills/ /usr/local/lib/brain-tools/claude-seed/skills/
COPY --chown=coder:coder brain-skills/ /usr/local/lib/brain-tools/claude-seed/skills/
COPY --chown=coder:coder hooks/ /usr/local/lib/brain-tools/hooks/
# Pre-create volume-mounted directories owned by coder so Docker inherits
# the right permissions on first mount (avoids root-owned dirs and silent failures).
RUN mkdir -p /home/coder/.claude /home/coder/.zsh-data \
    && chown coder:coder /home/coder/.claude /home/coder/.zsh-data

WORKDIR /brain
ENTRYPOINT ["/usr/local/lib/brain-tools/entrypoint.sh"]
