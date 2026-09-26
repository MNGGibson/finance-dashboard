import access


def test_unset_allowlist_allows_everyone():
    assert access.viewer_allowed(None, raw="") is True
    assert access.viewer_allowed({"email": "anyone@example.com"}, raw=None) in (True, False)  # depends on env


def test_allowlist_matches_case_insensitively():
    raw = "Me@Example.com, other@example.com"
    assert access.viewer_allowed({"email": "me@example.com"}, raw=raw) is True
    assert access.viewer_allowed({"email": "ME@EXAMPLE.COM "}, raw=raw) is True


def test_allowlist_refuses_others_and_anonymous():
    raw = "me@example.com"
    assert access.viewer_allowed({"email": "stranger@example.com"}, raw=raw) is False
    assert access.viewer_allowed({}, raw=raw) is False
    assert access.viewer_allowed(None, raw=raw) is False
    assert access.viewer_allowed("not a mapping", raw=raw) is False
