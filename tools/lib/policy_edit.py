"""The ONLY writer of auth policy. Every mutation is a git commit in the
profile clone — policy truth stays in the profile repo (world-machine
§9.7); the admin plane produces commits, never database rows."""
from __future__ import annotations

import os
import subprocess
import sys
import threading

import tomlkit


class PolicyEditError(Exception):
    pass


class PolicyEditor:
    # Serializes every operation within this process. The deployment shape
    # is a single API process, so this is sufficient to prevent concurrent
    # admin requests from racing a read-modify-write on profile.toml.
    # Cross-process serialization is git's problem (commit ordering /
    # conflicts) and is out of scope here.
    _lock = threading.Lock()

    def __init__(self, profile_dir: str):
        self.dir = profile_dir
        self.path = os.path.join(profile_dir, "profile.toml")
        if not os.path.isdir(os.path.join(profile_dir, ".git")):
            raise RuntimeError(
                f"{profile_dir} is not a git repository — the admin plane "
                "requires a cloned profile repo (brain-init --profile-repo).")

    # ── plumbing ─────────────────────────────────────────────────────

    def _read(self):
        with open(self.path, "r", encoding="utf-8") as f:
            return tomlkit.parse(f.read())

    def _rbac(self, doc, create: bool = False):
        auth = doc.get("auth")
        if auth is None:
            raise PolicyEditError("profile has no [auth] block")
        rbac = auth.get("rbac")
        if rbac is None:
            if not create:
                raise PolicyEditError("profile has no [auth.rbac] block")
            auth["rbac"] = tomlkit.table()
            rbac = auth["rbac"]
        return rbac

    def _commit(self, doc, message: str) -> str:
        run = lambda *a: subprocess.run(  # noqa: E731
            ["git", *a], cwd=self.dir, capture_output=True, text=True)
        new_text = tomlkit.dumps(doc)
        with open(self.path, "r", encoding="utf-8") as f:
            old_text = f.read()
        if new_text == old_text:
            # Idempotent no-op: nothing to write or commit — succeed with HEAD.
            return run("rev-parse", "HEAD").stdout.strip()
        with open(self.path, "w", encoding="utf-8") as f:
            f.write(new_text)
        run("add", "profile.toml")
        r = run("-c", "user.email=brain-admin@local",
                "-c", "user.name=brain-admin", "commit", "-m", message)
        if r.returncode != 0:
            # Roll back: a failed commit must never leave the mutated policy
            # live on disk (the provider hot-reads this file).
            with open(self.path, "w", encoding="utf-8") as f:
                f.write(old_text)
            run("add", "profile.toml")   # restore the index to match
            raise RuntimeError(f"git commit failed: {r.stderr.strip() or r.stdout.strip()}")
        sha = run("rev-parse", "HEAD").stdout.strip()
        if run("remote").stdout.strip():
            # Push stays inside the caller's _lock (this method is only ever
            # entered while holding it) — moving it out would change commit/
            # push ordering semantics more than this slice needs. What it DOES
            # need is a bounded wait: a hung network call must not block the
            # admin plane forever while the lock is held, so give push (and
            # ONLY push — commit/rev-parse are local and fast, and a timeout
            # there would be wrong) a timeout with a graceful warning.
            try:
                p = subprocess.run(
                    ["git", "push"], cwd=self.dir, capture_output=True,
                    text=True, timeout=30)
                if p.returncode != 0:
                    print(f"Warning: git push failed ({p.stderr.strip()}); "
                          "the commit is local — push manually or retry.",
                          file=sys.stderr)
            except subprocess.TimeoutExpired:
                print("Warning: git push timed out after 30s; "
                      "the commit is local — push manually or retry.",
                      file=sys.stderr)
        return sha

    # ── operations ───────────────────────────────────────────────────

    def role_set(self, name, read, write, admin: bool = False) -> str:
        if not isinstance(read, list) or not isinstance(write, list) \
                or not all(isinstance(x, str) for x in read + write):
            raise PolicyEditError("read/write must be lists of layer strings")
        with self._lock:
            doc = self._read()
            rbac = self._rbac(doc, create=True)
            roles = rbac.setdefault("roles", tomlkit.table())
            spec = tomlkit.table()
            spec["read"] = read
            spec["write"] = write
            if admin:
                spec["admin"] = True
            roles[name] = spec
            return self._commit(doc, f"policy: set role {name}")

    def role_rm(self, name) -> str:
        with self._lock:
            doc = self._read()
            rbac = self._rbac(doc)
            roles = rbac.get("roles", {})
            if name not in roles:
                raise PolicyEditError(f"unknown role: {name}")
            refs = [s for s, r in (rbac.get("identities") or {}).items() if r == name]
            refs += [p for p, r in (rbac.get("principals") or {}).items() if r == name]
            if rbac.get("default_role") == name:
                refs.append("default_role")
            if refs:
                raise PolicyEditError(
                    f"role {name} is still referenced by: {', '.join(refs)}")
            del roles[name]
            return self._commit(doc, f"policy: remove role {name}")

    def _set_mapping(self, table_name, key, role, action) -> str:
        with self._lock:
            doc = self._read()
            rbac = self._rbac(doc)
            if role is not None and role not in (rbac.get("roles") or {}):
                raise PolicyEditError(f"unknown role: {role}")
            table = rbac.setdefault(table_name, tomlkit.table())
            if role is None:
                if key not in table:
                    raise PolicyEditError(f"unknown {table_name[:-1]}: {key}")
                del table[key]
            else:
                table[key] = role
            return self._commit(doc, f"policy: {action}")

    def identity_map(self, subject, role) -> str:
        return self._set_mapping("identities", subject, role,
                                 f"map identity {subject} -> {role}")

    def identity_unmap(self, subject) -> str:
        return self._set_mapping("identities", subject, None,
                                 f"unmap identity {subject}")

    def principal_set(self, pid, role) -> str:
        return self._set_mapping("principals", pid, role,
                                 f"map principal {pid} -> {role}")

    def principal_rm(self, pid) -> str:
        return self._set_mapping("principals", pid, None,
                                 f"remove principal {pid}")

    def default_role_set(self, role) -> str:
        with self._lock:
            doc = self._read()
            rbac = self._rbac(doc)
            if role not in (rbac.get("roles") or {}):
                raise PolicyEditError(f"unknown role: {role}")
            rbac["default_role"] = role
            return self._commit(doc, f"policy: default role -> {role}")
