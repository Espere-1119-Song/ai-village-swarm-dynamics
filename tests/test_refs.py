import hashlib
import time

import polars as pl
import pytest

from avsd.events.refs import (
    KEEP_OWNERS,
    SALT_FILE,
    extract_refs,
    extract_refs_batch,
    hash_owner,
    is_secret_param,
    normalize_path,
    normalize_url,
    owner_salt,
    ref_type,
    set_owner_salt,
)

DOC_ID = "1AbCdEfGhIjKlMnOpQrStUvWxYz0123456789_-xyZ"
FORM_ID = "1FAIpQLSdAbCdEfGhIjKlMnOpQrStUvWxYz0123456789"
SALT = b"unit-test-salt-0123456789abcdef"
# A synthetic JWT: {"alg":"HS256"} . {"sub":"1234567890"} . "signature_123".
JWT = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.c2lnbmF0dXJlXzEyMw"


@pytest.fixture(autouse=True)
def _fixed_salt():
    """Owner pseudonyms use a test secret, never the project file under data/."""
    set_owner_salt(SALT)
    yield
    set_owner_salt(None)


# --- normalize_url -------------------------------------------------------------
@pytest.mark.parametrize(
    "url, expected",
    [
        ("HTTPS://Example.COM/Path/To", "https://example.com/Path/To"),
        ("https://example.com/a#section-2", "https://example.com/a"),
        ("https://example.com/a/", "https://example.com/a"),
        ("https://example.com/", "https://example.com"),
        ("https://example.com:443/a", "https://example.com/a"),
        ("http://example.com:80/a", "http://example.com/a"),
        ("http://localhost:3000/api/x", "http://localhost:3000/api/x"),
        ("https://example.com//a///b", "https://example.com/a/b"),
        # tracking parameters dropped, others kept in order with their encoding
        (
            "https://example.com/p?b=2&utm_source=x&a=1&fbclid=Z&gclid=Q&q=hello%20world&utm_medium=m",
            "https://example.com/p?b=2&a=1&q=hello%20world",
        ),
        ("https://youtu.be/abcdefghijk?si=TRACK", "https://youtu.be/abcdefghijk"),
        ("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=42", "https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=42"),
        ("https://x.com/u/status/1?ref_src=twsrc&igshid=1&mc_cid=a&mc_eid=b&spm=c", "https://x.com/u/status/1"),
        ("https://example.com/a?&amp;b=1&amp;utm_campaign=z", "https://example.com/a?b=1"),
        # cache busters and unexpanded shell values
        ("https://site.example/feed.xml?cb=$(date", "https://site.example/feed.xml"),
        ("https://site.example/index.html?v=1727712000&page=2", "https://site.example/index.html?page=2"),
        ("https://site.example/index.html?nocache=1&_=17", "https://site.example/index.html"),
        # credentials never survive
        ("https://oauth2:glpat-abcdefghijklmnopqrst@gitlab.example/x", "https://gitlab.example/x"),
        ("https://api.example.com/v1/items?token=s3cr3t&id=7", "https://api.example.com/v1/items?id=7"),
        ("https://hooks.example.com/ghp_abcdefghijklmnop1234/x", "https://hooks.example.com/REDACTED/x"),
        # trailing punctuation and brackets
        ("https://example.com/a).", "https://example.com/a"),
        ("https://en.wikipedia.org/wiki/Foo_(bar)", "https://en.wikipedia.org/wiki/Foo_(bar)"),
        ("<https://example.com/a>", "https://example.com/a"),
        ("https://example.com/a',", "https://example.com/a"),
        ("www.Example.com/x", "https://www.example.com/x"),
        # templates and junk
        ("https://{host}/api", None),
        ("https://localhost:XXXX/a", None),
        ("https://example.com/items/${ID}/view", "https://example.com/items"),
        ("ftp://example.com/x", None),
        ("https://nodot/x", None),
    ],
)
def test_normalize_url_generic(url, expected):
    assert normalize_url(url) == expected


@pytest.mark.parametrize(
    "url, expected",
    [
        (f"https://docs.google.com/document/d/{DOC_ID}/edit?usp=sharing#heading=h.1", f"gdoc:document:{DOC_ID}"),
        (f"https://docs.google.com/spreadsheets/d/{DOC_ID}/edit#gid=0", f"gdoc:spreadsheets:{DOC_ID}"),
        (f"https://docs.google.com/spreadsheets/u/0/d/{DOC_ID}/export?format=csv", f"gdoc:spreadsheets:{DOC_ID}"),
        (f"https://docs.google.com/presentation/d/{DOC_ID}/", f"gdoc:presentation:{DOC_ID}"),
        (f"https://docs.google.com/forms/d/e/{FORM_ID}/viewform?entry.1=x", f"gdoc:forms:{FORM_ID}"),
        (f"https://docs.google.com/a/example.org/document/d/{DOC_ID}/edit", f"gdoc:document:{DOC_ID}"),
        (f"https://drive.google.com/file/d/{DOC_ID}/view?usp=drive_link", f"gdoc:file:{DOC_ID}"),
        (f"https://drive.google.com/open?id={DOC_ID}", f"gdoc:file:{DOC_ID}"),
        (f"https://drive.google.com/uc?export=download&id={DOC_ID}", f"gdoc:file:{DOC_ID}"),
        (f"https://drive.google.com/drive/u/0/folders/{DOC_ID}", f"gdoc:folder:{DOC_ID}"),
        ("https://docs.google.com/document/d/FILE_ID/edit", None),  # placeholder id
        ("https://docs.google.com/spreadsheets/d/{SHEET_ID}/edit", None),
        ("https://docs.google.com/forms", "https://docs.google.com/forms"),
    ],
)
def test_normalize_url_gdoc(url, expected):
    assert normalize_url(url) == expected


@pytest.mark.parametrize(
    "url, expected",
    [
        ("https://github.com/AI-Village-Agents/Repo", "github:ai-village-agents/repo"),
        ("https://github.com/ai-village-agents/repo.git", "github:ai-village-agents/repo"),
        ("https://www.github.com/o/r/", "github:o/r"),
        ("https://github.com/o/r/blob/main/src/App.tsx#L10", "github:o/r/src/App.tsx"),
        ("https://github.com/o/r/tree/main/docs", "github:o/r/docs"),
        ("https://github.com/o/r/tree/main", "github:o/r"),
        ("https://github.com/o/r/raw/main/a%20b.md", "github:o/r/a b.md"),
        ("https://github.com/o/r/issues/12#issuecomment-9", "github:o/r/issues/12"),
        ("https://github.com/o/r/pull/34/files", "github:o/r/pull/34"),
        ("https://github.com/o/r/commit/ABCDEF1234", "github:o/r/commit/abcdef1234"),
        ("https://github.com/o/r/actions/runs/123", "github:o/r"),
        ("https://github.com/o/r/issues/new", "github:o/r"),
        ("https://github.com/o", "github:o"),
        ("https://github.com/orgs/ai-village-agents/repositories", "github:ai-village-agents"),
        ("https://github.com/settings/tokens", "https://github.com/settings/tokens"),
        ("https://github.com/search?q=x", "https://github.com/search?q=x"),
        ("https://github.com/ai‑village‑agents/r", "github:ai-village-agents/r"),
        ("https://github.com/o/r)", "github:o/r"),
        ("https://github.com/o/r.git@v1.2#egg=pkg", "github:o/r"),
        ("https://raw.githubusercontent.com/o/r/main/data/x.json", "github:o/r/data/x.json"),
        ("https://raw.githubusercontent.com/o/r/refs/heads/main/x.py", "github:o/r/x.py"),
        ("https://api.github.com/repos/o/r/contents/docs/a.md?ref=dev", "github:o/r/docs/a.md"),
        ("https://api.github.com/repos/o/r/pulls/5", "github:o/r/pull/5"),
        ("https://api.github.com/repos/o/r/commits?per_page=5", "github:o/r"),
        ("https://api.github.com/orgs/ai-village-agents/repos", "github:ai-village-agents"),
        ("https://ai-village-agents.github.io/site/page.html", "https://ai-village-agents.github.io/site/page.html"),
        ("https://gitlab.com/ai-village-agents/repo", "gitlab:ai-village-agents/repo"),
        ("https://gitlab.com/g/sub/repo.git", "gitlab:g/sub/repo"),
        ("https://gitlab.com/g/sub/repo/-/blob/main/a/b.md", "gitlab:g/sub/repo/a/b.md"),
        ("https://gitlab.com/g/repo/-/raw/main/x.json?inline=false", "gitlab:g/repo/x.json"),
        ("https://gitlab.com/g/repo/-/tree/main", "gitlab:g/repo"),
        ("https://gitlab.com/g/repo/-/merge_requests/7/diffs", "gitlab:g/repo/merge_requests/7"),
        ("https://gitlab.com/g/repo/-/commit/0123abcd", "gitlab:g/repo/commit/0123abcd"),
        ("https://gitlab.com/g/repo/-/pipelines", "gitlab:g/repo"),
        ("https://gitlab.com/g/repo/blob/main/x.md", "gitlab:g/repo/x.md"),
        ("https://gitlab.com/groups/g/sub/-/issues", "gitlab:g/sub"),
        ("https://gitlab.com/api/v4/projects/g%2Fsub%2Frepo/repository/files/docs%2Fa.md/raw?ref=main",
         "gitlab:g/sub/repo/docs/a.md"),
        ("https://gitlab.com/api/v4/projects/g%2Frepo/merge_requests/3/notes", "gitlab:g/repo/merge_requests/3"),
        ("https://gitlab.com/api/v4/projects/12345/repository/files/a.md", "gitlab-pid:12345/a.md"),
        ("https://gitlab.com/api/v4/projects/12345/pipelines", "gitlab-pid:12345"),
        ("https://gitlab.com/users/sign_in", "https://gitlab.com/users/sign_in"),
        ("https://site-1a2b3c.gitlab.io/page", "https://site-1a2b3c.gitlab.io/page"),
    ],
)
def test_normalize_url_git_hosts(url, expected):
    assert normalize_url(url) == expected


# --- normalize_path --------------------------------------------------------------
@pytest.mark.parametrize(
    "path, expected",
    [
        ("/home/computeruse/work//notes.md", "path:~/work/notes.md"),
        ("~/work/notes.md.", "path:~/work/notes.md"),
        ("$HOME/work/a.py", "path:~/work/a.py"),
        ("${HOME}/work/a.py", "path:~/work/a.py"),
        ("/tmp/out/", "path:/tmp/out"),
        ("/tmp/a/./b/../c.txt),", "path:/tmp/a/c.txt"),
        ("./scripts/run.sh", "path:./scripts/run.sh"),
        ("../src/app.js", "path:../src/app.js"),
        ("/workspace/proj/x", "path:/workspace/proj/x"),
        ("/home/ubuntu/x", "path:/home/ubuntu/x"),
        ("/tmp", None),
        ("/home/computeruse", None),
        ("~/", None),
        ("../..", None),
        ("/dev/null", None),
        ("/usr/bin/env", None),
        ("/api/v1/users", None),
        ("/articles/2025/04/02/post", None),
        ("and/or", None),
    ],
)
def test_normalize_path(path, expected):
    assert normalize_path(path) == expected


# --- extract_refs ---------------------------------------------------------------
def test_extract_mixed_text_order_and_dedup():
    text = (
        "See https://github.com/ai-village-agents/site/blob/main/index.html and "
        f"[the doc](https://docs.google.com/document/d/{DOC_ID}/edit). Saved to ~/notes/plan.md, "
        "also https://github.com/ai-village-agents/site/blob/main/index.html#top again; "
        "and/or the 2025/04/02 numbers (1/2, 3/4)."
    )
    assert extract_refs(text) == [
        "github:ai-village-agents/site/index.html",
        f"gdoc:document:{DOC_ID}",
        "path:~/notes/plan.md",
    ]


def test_extract_markdown_and_brackets():
    text = "[https://a.example/x](https://b.example/y) and (see https://c.example/z)."
    assert extract_refs(text) == ["https://a.example/x", "https://b.example/y", "https://c.example/z"]


def test_extract_bare_hosts():
    text = "visit www.example.org/page, the repo github.com/o/r and api.github.com/repos/x/y"
    assert extract_refs(text) == ["https://www.example.org/page", "github:o/r"]


def test_extract_url_paths_not_paths():
    text = "curl -s https://example.com/tmp/x.json > /tmp/x.json && cat /tmp/x.json"
    assert extract_refs(text) == ["https://example.com/tmp/x.json", "path:/tmp/x.json"]


def test_extract_paths_in_commands():
    text = (
        "cd /home/computeruse/proj && python3 ./scripts/build.py --out=/tmp/build/out.html "
        'PATH=/usr/bin:/opt/tool/bin echo "done" >/dev/null 2>&1; ls ../shared/'
    )
    assert extract_refs(text) == [
        "path:~/proj",
        "path:./scripts/build.py",
        "path:/tmp/build/out.html",
        "path:/opt/tool/bin",
        "path:../shared",
    ]


def test_extract_html_and_routes_are_not_paths():
    text = '<a href="/articles/1">x</a></div> GET /api/v1/items s/foo/bar/g km/h 50/50'
    assert extract_refs(text) == []


def test_extract_git_remotes():
    text = "\n".join([
        "git clone https://github.com/o/r.git ~/r",
        "git clone git@github.com:Owner2/Repo2.git",
        "git remote add origin https://oauth2:${TOKEN}@gitlab.com/g/sub/proj.git",
        "git remote set-url up git@gitlab.com:g/other.git",
        "gh repo clone o3/r3 -- --depth 1",
        "gh pr list -R o4/r4 --state open",
        "gh issue view 3 --repo=o5/r5",
        "glab mr list -R g6/sub/r6",
        "gh api repos/o7/r7/contents/README.md --jq .content",
        'glab api "projects/g8%2Fr8/repository/files/a%2Fb.md/raw?ref=main"',
        "gh api repos/{owner}/{repo}/pulls",
    ])
    assert extract_refs(text) == [
        "github:o/r",
        "path:~/r",
        "github:owner2/repo2",
        "gitlab:g/sub/proj",
        "gitlab:g/other",
        "github:o3/r3",
        "github:o4/r4",
        "github:o5/r5",
        "gitlab:g6/sub/r6",
        "github:o7/r7/README.md",
        "gitlab:g8/r8/a/b.md",
    ]


def test_extract_json_and_negatives():
    text = (
        '{"url":"https://example.com/a","path":"/tmp/x.json","n":"1/2"} '
        "mail someone@example.com or someone@www.example.com, "
        f"truncated https://docs.google.com/document/d/1G6Gsqn\u2026 and "
        "pip install git+https://github.com/o/r.git@main and github.com/ai\u2011village\u2011agents/x"
    )
    assert extract_refs(text) == [
        "https://example.com/a",
        "path:/tmp/x.json",
        "github:o/r",
        "github:ai-village-agents/x",
    ]


def test_extract_no_credentials():
    text = "git push https://x-access-token:ghp_abcdefghijklmnopqrstuvwx@github.com/o/r.git main"
    refs = extract_refs(text)
    assert refs == ["github:o/r"]
    assert "ghp_" not in "".join(refs)


def test_extract_empty_and_null():
    assert extract_refs("") == []
    assert extract_refs(None) == []
    assert extract_refs("nothing to see here") == []


def test_batch_matches_single_and_handles_nulls():
    texts = pl.Series(
        "content",
        ["see https://example.com/a?utm_source=x", None, "", "~/a.md and ~/a.md", "no refs"],
    )
    out = extract_refs_batch(texts)
    assert out.dtype == pl.List(pl.String)
    assert out.len() == texts.len()
    assert out.to_list() == [["https://example.com/a"], [], [], ["path:~/a.md"], []]
    for t, refs in zip(texts.to_list(), out.to_list()):
        assert extract_refs(t) == refs


def test_batch_empty_series():
    out = extract_refs_batch(pl.Series("x", [], dtype=pl.String))
    assert out.len() == 0 and out.dtype == pl.List(pl.String)
    out = extract_refs_batch(pl.Series("x", [None, None], dtype=pl.String))
    assert out.to_list() == [[], []]


def test_batch_speed_synthetic():
    base = [
        "see https://github.com/ai-village-agents/r{i}/blob/main/x{i}.md and ~/work/f{i}.txt",
        "curl -s 'https://api.example.com/v1/q?id={i}&utm_source=z' > /tmp/q{i}.json",
        "plain chat message number {i} with no refs at all, and/or 1/2",
    ]
    texts = pl.Series([b.format(i=i) for i in range(20_000) for b in base])
    t0 = time.perf_counter()
    out = extract_refs_batch(texts)
    dt = time.perf_counter() - t0
    assert out.list.len().sum() == 20_000 * 4
    assert dt < 30


# --- hash_owner / ref_type --------------------------------------------------------
def test_hash_owner():
    assert hash_owner("github:ai-village-agents/site/a.md", KEEP_OWNERS) == "github:ai-village-agents/site/a.md"
    assert hash_owner("gitlab:ai-village-agents/x", {"ai-village-agents"}) == "gitlab:ai-village-agents/x"
    assert hash_owner("github:o3-ux/site") == "github:o3-ux/site"  # agent account, default keep set
    assert hash_owner("github:o3-ux/site", {"ai-village-agents"}).startswith("github:owner_")
    h = hash_owner("github:someone/someone.github.io/index.html", {"ai-village-agents"})
    assert h.startswith("github:owner_") and "someone" not in h
    assert h.endswith(".github.io/index.html")
    assert hash_owner("github:someone", set()) == h.split("/")[0]
    g = hash_owner("gitlab:grp/sub/repo", set())
    assert g.split("/", 1)[1] == "sub/repo" and len(g.split("/")[0]) == len("gitlab:owner_") + 10
    assert hash_owner("https://someone.github.io/p", set()).startswith("https://owner_")
    assert hash_owner("https://site-1a2b3c.gitlab.io/p", set()) == "https://site-1a2b3c.gitlab.io/p"
    assert hash_owner("path:/home/someone/x", set()).startswith("path:/home/owner_")
    assert hash_owner("path:/home/ubuntu/x", set()) == "path:/home/ubuntu/x"
    assert hash_owner("https://example.com/x", set()) == "https://example.com/x"
    assert hash_owner("gdoc:document:abc", set()) == "gdoc:document:abc"


def test_hash_owner_pages_host_any_suffix():
    owner = hash_owner("github:someone", set())[len("github:"):]
    # normalize_url drops the root slash, so a query can follow the host directly.
    assert normalize_url("https://someone.github.io/?x=1") == "https://someone.github.io?x=1"
    cases = {
        "https://someone.github.io?x=1": f"https://{owner}.github.io?x=1",
        "https://someone.github.io#top": f"https://{owner}.github.io#top",
        "https://someone.github.io": f"https://{owner}.github.io",
        "https://someone.github.io/": f"https://{owner}.github.io/",
        "https://someone.github.io:8443/a?b=1": f"https://{owner}.github.io:8443/a?b=1",
        "http://www.someone.github.io/a": f"http://{owner}.github.io/a",
        "https://someone.gitlab.io?x=1": f"https://{owner}.gitlab.io?x=1",
    }
    for ref, want in cases.items():
        assert hash_owner(ref, set()) == want, ref
        assert "someone" not in ref_type(ref)
    assert ref_type(normalize_url("https://someone.github.io/?x=1")) == f"url:{owner}.github.io"
    kept = "https://ai-village-agents.github.io?x=1"
    assert hash_owner(kept) == kept and ref_type(kept) == "url:ai-village-agents.github.io"
    assert hash_owner("https://site-1a2b3c.gitlab.io?x=1", set()) == "https://site-1a2b3c.gitlab.io?x=1"
    assert hash_owner("https://github.io/x", set()) == "https://github.io/x"
    assert hash_owner("https://example.com/someone.github.io", set()) == "https://example.com/someone.github.io"


def test_hash_owner_user_dirs():
    owner = hash_owner("github:someone", set())[len("github:"):]
    assert hash_owner("path:/Users/someone/x", set()) == f"path:/Users/{owner}/x"
    assert hash_owner("path:/Users/Someone", set()) == f"path:/Users/{owner}"
    assert hash_owner("path:/home/someone/x", set()) == f"path:/home/{owner}/x"
    assert hash_owner("path:/mnt/c/Users/someone/a b.txt", set()) == f"path:/mnt/c/Users/{owner}/a b.txt"
    assert hash_owner("path:/media/someone/usb/a.txt", set()) == f"path:/media/{owner}/usb/a.txt"
    for generic in ("path:/Users/Shared/x", "path:/Users/username/x", "path:/home/runner/work/x",
                    "path:/home/Ubuntu/x", "path:/tmp/someone/x", "path:~/someone/x"):
        assert hash_owner(generic, set()) == generic, generic


def test_owner_hash_is_keyed():
    plain_sha1 = "owner_" + hashlib.sha1(b"someone").hexdigest()[:10]
    a = hash_owner("github:someone/r", set(), salt=b"a" * 16)
    b = hash_owner("github:someone/r", set(), salt=b"b" * 16)
    assert a != b and a == hash_owner("github:SomeOne/r".lower(), set(), salt=b"a" * 16)
    assert plain_sha1 not in (a, b, hash_owner("github:someone/r", set()))
    assert hash_owner("github:someone/r", set()) == hash_owner("github:someone/r", set(), salt=SALT)


def test_owner_salt_file_created_once(tmp_path, monkeypatch):
    monkeypatch.setattr("avsd.config.load_config", lambda *a, **k: {"paths": {"interim": tmp_path}})
    set_owner_salt(None)
    s1 = owner_salt()
    path = tmp_path / SALT_FILE
    assert path.read_bytes() == s1 and len(s1) == 32 and (path.stat().st_mode & 0o777) == 0o600
    set_owner_salt(None)
    assert owner_salt() == s1  # read back, not regenerated
    assert [p.name for p in tmp_path.iterdir()] == [SALT_FILE]


def test_credential_params_and_jwt():
    url = ("https://api.example.com/v1/x?api-key=abcdefgh12345678&x-signature=zz&access_key=k&"
           "dd-api-key=q&api_token=t&claim_token=c&Client-Secret=s&jwt=j&session_id=9&pass=p&"
           "id=7&token_id=5&max_tokens=10&page=2")
    assert normalize_url(url) == "https://api.example.com/v1/x?id=7&token_id=5&max_tokens=10&page=2"
    for key in ("API-Key", "x-amz-security-token", "X-Goog-Credential", "access-token", "authKey",
                "private_key", "id%5Ftoken"):
        assert is_secret_param(key), key
    for key in ("q", "keyword", "token_id", "tokenType", "monkey", "page"):
        assert not is_secret_param(key), key
    assert normalize_url(f"https://example.com/dl/{JWT}/file.zip") == "https://example.com/dl/REDACTED/file.zip"
    assert normalize_url(f"https://assets.example.com/a?sp=r&jwt={JWT}&x=1") == "https://assets.example.com/a?sp=r&x=1"
    assert normalize_url(f"https://example.com/a?state={JWT}") == "https://example.com/a?state=REDACTED"
    assert normalize_path(f"/tmp/{JWT}.txt") == "path:/tmp/REDACTED.txt"
    assert extract_refs(f"curl https://example.com/s/{JWT} -o /tmp/out") == [
        "https://example.com/s/REDACTED", "path:/tmp/out"]


def test_ref_type():
    assert ref_type("github:o/r") == "github"
    assert ref_type("gitlab-pid:1") == "gitlab-pid"
    assert ref_type(f"gdoc:forms:{FORM_ID}") == "gdoc:forms"
    assert ref_type("path:~/a/b") == "path:~"
    assert ref_type("path:./a") == "path:."
    assert ref_type("path:/tmp/a") == "path:/tmp"
    assert ref_type("https://Sub.example.com:8080/x") == "url:sub.example.com"
    assert ref_type("https://someone.github.io/x").startswith("url:owner_")
