from lib.visibility import visible, can_write, filter_visible
from lib.auth import Principal, OWNER
from lib.profile import Field

FIELDS = [Field("known_by", "list", "Known by", visibility="allow"),
          Field("never_tell", "list", "Never tell", visibility="deny")]


def _p(read, write, role="agent"):
    return Principal(id="a", role=role, read_layers=tuple(read),
                     write_layers=tuple(write), kind="static")


def test_owner_sees_everything():
    assert visible({"layer": "secret", "never_tell": ["owner"]}, OWNER, FIELDS)


def test_coarse_layer_wall():
    p = _p(["fiction"], [])
    assert visible({"layer": "fiction"}, p, FIELDS)
    assert not visible({"layer": "meta"}, p, FIELDS)      # layer not allowed
    assert not visible({}, p, FIELDS)                     # missing layer, restricted → deny


def test_fine_allow_field():
    p = _p(["fiction"], [], role="fenn")
    # allowlist populated and role not in it → hidden
    assert not visible({"layer": "fiction", "known_by": ["mira"]}, p, FIELDS)
    # role in allowlist → visible
    assert visible({"layer": "fiction", "known_by": ["fenn"]}, p, FIELDS)
    # empty/absent allowlist → no restriction
    assert visible({"layer": "fiction"}, p, FIELDS)


def test_fine_deny_field():
    p = _p(["fiction"], [], role="fenn")
    assert not visible({"layer": "fiction", "never_tell": ["fenn"]}, p, FIELDS)
    assert visible({"layer": "fiction", "never_tell": ["mira"]}, p, FIELDS)


def test_can_write():
    assert can_write({"layer": "a"}, _p(["a", "b"], ["a"]))
    assert not can_write({"layer": "b"}, _p(["a", "b"], ["a"]))   # read b, but not write b
    assert can_write({"layer": "anything"}, OWNER)


def test_filter_visible():
    p = _p(["fiction"], [], role="fenn")
    items = [{"m": {"layer": "fiction"}}, {"m": {"layer": "meta"}}]
    kept = filter_visible(items, p, FIELDS, meta_of=lambda i: i["m"])
    assert kept == [items[0]]


def test_deny_beats_allow():
    p = _p(["fiction"], [], role="fenn")
    # both fields present: deny wins even if allow would permit
    assert not visible({"layer": "fiction", "known_by": ["fenn"], "never_tell": ["fenn"]}, p, FIELDS)


def test_anonymous_denies_all():
    p = _p([], [])                       # read_layers=()
    assert not visible({"layer": "fiction"}, p, FIELDS)
    assert not visible({}, p, FIELDS)


def test_scalar_and_list_field_equivalent():
    p = _p(["fiction"], [], role="fenn")
    assert visible({"layer": "fiction", "known_by": "fenn"}, p, FIELDS) == \
           visible({"layer": "fiction", "known_by": ["fenn"]}, p, FIELDS)   # both True
    assert not visible({"layer": "fiction", "known_by": "mira"}, p, FIELDS) # scalar non-member hides


def test_empty_allow_list_does_not_hide():
    p = _p(["fiction"], [], role="fenn")
    assert visible({"layer": "fiction", "known_by": []}, p, FIELDS)


def test_role_not_id_match():
    # principal id equals a role name; must NOT false-match on id
    from lib.auth import Principal
    p = Principal(id="fenn", role="agent", read_layers=("fiction",), write_layers=(), kind="static")
    assert not visible({"layer": "fiction", "known_by": ["fenn"]}, p, FIELDS)  # id in list, role not


def test_missing_and_nonstring_layer_deny_closed():
    p = _p(["fiction"], [])
    assert not visible({}, p, FIELDS)                    # missing
    assert not visible({"layer": ""}, p, FIELDS)         # blank
    assert not visible({"layer": None}, p, FIELDS)       # None
    assert not visible({"layer": 123}, p, FIELDS)        # non-string, not in allowlist


def test_malformed_meta_does_not_crash():
    p = _p(["fiction"], [], role="fenn")
    assert visible({}, p, FIELDS) is False               # no raise, fails closed
    assert isinstance(visible({"layer": "fiction", "known_by": {"a": 1}}, p, FIELDS), bool)


def test_string_read_layers_fails_closed():
    from lib.auth import Principal
    bad = Principal(id="x", role="x", read_layers="fic*tion", write_layers="*", kind="static")
    assert visible({"layer": "nope"}, bad, FIELDS) is False   # string must NOT bypass
    from lib.visibility import can_write
    assert can_write({"layer": "nope"}, bad) is False
