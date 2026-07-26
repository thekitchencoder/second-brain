# Recipe: browser IDE (code-server) on top of second-brain

The `:ui` image is deprecated (last published: 1.1.x). code-server and
Claude Code move fast; bundling them meant shipping their release
cadence. Instead, own a thin layer yourself:

```dockerfile
# Dockerfile.my-ui
FROM kitchencoder/second-brain:latest

ARG CODE_SERVER_VERSION=4.101.2
RUN curl -fsSL https://code-server.dev/install.sh \
    | sh -s -- --version ${CODE_SERVER_VERSION} \
    && npm install -g @anthropic-ai/claude-code

EXPOSE 7778
ENTRYPOINT ["/bin/sh", "-c", "\
    /usr/local/lib/brain-tools/entrypoint.sh & \
    exec code-server --bind-addr 0.0.0.0:7778 --auth password /brain"]
```

```bash
docker build -f Dockerfile.my-ui -t my-brain-ui .
docker run -d --name brain \
  -v /path/to/your/brain:/brain \
  -p 7778:7778 -p 7779:7779 -p 7780:7780 \
  -e PASSWORD=choose-a-password \
  my-brain-ui
```

Update `CODE_SERVER_VERSION` (and rebuild) on your own schedule. The
brain services behave exactly as in the base image — see the user guide.
