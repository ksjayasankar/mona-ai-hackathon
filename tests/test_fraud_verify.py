import json

import services.fraud as svc


def test_parse_github_handle_variants():
    assert svc.parse_github_handle("https://github.com/torvalds") == "torvalds"
    assert svc.parse_github_handle("github.com/torvalds/") == "torvalds"
    assert svc.parse_github_handle("@torvalds") == "torvalds"
    assert svc.parse_github_handle("torvalds") == "torvalds"
    assert svc.parse_github_handle(None) is None


def test_github_lookup_parses_account_age_and_languages(monkeypatch):
    class _Resp:
        def __init__(self, payload):
            self._p = payload

        def raise_for_status(self):
            pass

        def json(self):
            return self._p

    def fake_get(url, **kw):
        if url.endswith("/users/jane"):
            return _Resp({"created_at": "2022-06-20T00:00:00Z", "public_repos": 3})
        if "/repos" in url:
            return _Resp([{"language": "Python"}, {"language": "Python"}, {"language": "Go"}])
        return _Resp({})

    monkeypatch.setattr(svc.httpx, "get", fake_get)
    out = json.loads(svc.github_lookup("jane"))
    assert out["account_age_years"] >= 3.9  # 2022-06-20 -> 2026-06-20 ≈ 4y
    assert "Python" in out["languages"]


def test_github_lookup_handles_missing_user(monkeypatch):
    import httpx as _httpx

    def fake_get(url, **kw):
        raise _httpx.HTTPError("404")

    monkeypatch.setattr(svc.httpx, "get", fake_get)
    out = svc.github_lookup("nope")
    assert "error" in out.lower() or "not" in out.lower()  # graceful, no raise
