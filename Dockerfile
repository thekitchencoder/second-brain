FROM python:3.12-slim

LABEL version="0.2.5"

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

# Brain tools
COPY tools/ /usr/local/lib/brain-tools/
COPY zk/ /usr/local/lib/brain-tools/zk/
RUN chmod +x /usr/local/lib/brain-tools/brain-index \
              /usr/local/lib/brain-tools/brain-search \
              /usr/local/lib/brain-tools/brain-mcp-server \
              /usr/local/lib/brain-tools/brain-init \
              /usr/local/lib/brain-tools/brain-template-sync \
              /usr/local/lib/brain-tools/entrypoint.sh

# Shell environment
COPY tools/brain.zshrc /root/.zshrc

# Add tools to PATH and Python path
ENV PATH="/usr/local/lib/brain-tools:$PATH"
ENV PYTHONPATH="/usr/local/lib/brain-tools"

WORKDIR /brain
ENTRYPOINT ["/usr/local/lib/brain-tools/entrypoint.sh"]
CMD ["zsh"]
