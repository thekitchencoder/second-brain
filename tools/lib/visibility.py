"""Visibility / write-authorization predicates — the Seam 7 choke point.

Every content-egress path routes read results through visible(); every write
handler gates on can_write(). Role-based and profile-driven: a coarse layer
wall (read_layers/write_layers) then fine allow/deny fields matched on the
caller's role. mode=none / owner (layers ("*",)) short-circuit to allow, so
non-RBAC brains pay nothing.

NOTE (deferred): the per-principal retrieval/audit log hooks in HERE, at the
single choke point, once the RBAC-tier store exists. Do not add it in Plan E.
"""
from __future__ import annotations


def _as_list(v) -> list:
    if isinstance(v, list):
        return [str(x) for x in v]
    return [str(v)] if v else []


def _unrestricted(layers) -> bool:
    # Only a real collection containing "*" is unrestricted. A non-collection
    # (e.g. a stray string) fails CLOSED, never open, on this gate.
    return isinstance(layers, (tuple, list, set, frozenset)) and "*" in layers


def _layer_ok(note_layer, allowed: tuple) -> bool:
    if "*" in allowed:
        return True
    if not note_layer:
        return False                     # deny-by-default on missing layer
    return note_layer in allowed


def visible(meta: dict, principal, fields) -> bool:
    read_layers = principal.read_layers
    if not isinstance(read_layers, (tuple, list, set, frozenset)):
        return False                     # malformed principal → deny
    if _unrestricted(read_layers):
        return True                      # owner / unrestricted read
    if not _layer_ok(meta.get("layer"), read_layers):
        return False                     # coarse wall
    for f in fields or []:
        if not getattr(f, "visibility", ""):
            continue
        vals = _as_list(meta.get(f.name))
        if f.visibility == "allow":
            if vals and principal.role not in vals:
                return False             # allowlist present, role absent
        elif f.visibility == "deny":
            if principal.role in vals:
                return False             # explicitly denied
    return True


def can_write(meta: dict, principal) -> bool:
    write_layers = principal.write_layers
    if not isinstance(write_layers, (tuple, list, set, frozenset)):
        return False                     # malformed principal → deny
    if _unrestricted(write_layers):
        return True
    return _layer_ok(meta.get("layer"), write_layers)


def filter_visible(items, principal, fields, meta_of):
    return [it for it in items if visible(meta_of(it), principal, fields)]


def can_write_transition(old_meta: dict, new_meta: dict, principal) -> bool:
    """A write may only land content whose layer the caller can write, AND must
    be allowed to write the note's current layer. Both sides gate — so a caller
    cannot move a note into (or out of) a layer it isn't authorised for."""
    return can_write(old_meta, principal) and can_write(new_meta, principal)
