FROM python:3.12-slim

ARG ZK_VERSION=0.14.1

# System tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    fzf \
    ripgrep \
    bat \
    zsh \
    git \
    && rm -rf /var/lib/apt/lists/* \
    && ln -s /usr/bin/batcat /usr/local/bin/bat

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

# Python dependencies
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# Vault tools
COPY tools/ /usr/local/lib/vault-tools/
COPY zk/ /usr/local/lib/vault-tools/zk/
RUN chmod +x /usr/local/lib/vault-tools/vault-index \
              /usr/local/lib/vault-tools/vault-search \
              /usr/local/lib/vault-tools/vault-mcp-server \
              /usr/local/lib/vault-tools/vault-init

# Add tools to PATH and Python path
ENV PATH="/usr/local/lib/vault-tools:$PATH"
ENV PYTHONPATH="/usr/local/lib/vault-tools"

WORKDIR /vault
CMD ["zsh"]
