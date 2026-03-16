FROM python:3.12-slim

LABEL version="0.1.0"

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

# Python dependencies (install without sqlite-vec first, then build sqlite-vec from source)
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir $(grep -v sqlite-vec /tmp/requirements.txt | tr '\n' ' ')

# Build sqlite-vec from source (PyPI aarch64 wheel contains a 32-bit binary)
ARG SQLITE_VEC_VERSION=0.1.6
RUN apt-get update && apt-get install -y --no-install-recommends gcc libsqlite3-dev wget \
    && cd /tmp \
    && wget -q "https://github.com/asg017/sqlite-vec/releases/download/v${SQLITE_VEC_VERSION}/sqlite-vec-${SQLITE_VEC_VERSION}-amalgamation.tar.gz" \
    && tar xzf "sqlite-vec-${SQLITE_VEC_VERSION}-amalgamation.tar.gz" \
    && pip install --no-cache-dir "sqlite-vec>=${SQLITE_VEC_VERSION}" \
    && gcc -shared -fPIC -I/usr/include -o /usr/local/lib/python3.12/site-packages/sqlite_vec/vec0.so sqlite-vec.c -lm \
    && apt-get remove -y gcc libsqlite3-dev wget \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/* /tmp/sqlite-vec*

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
