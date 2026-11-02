from app.helper import _commit_fingerprint, _edits_already_applied, _edits_overlap, _three_way_merge

BASE = ["a\n", "b\n", "c\n", "d\n"]


def test_disjoint_edits_are_combined():
    ours = ["a\n", "B\n", "c\n", "d\n"]
    theirs = ["a\n", "b\n", "c\n", "D\n"]

    merged, conflict = _three_way_merge(BASE, ours, theirs)

    assert not conflict
    assert merged == ["a\n", "B\n", "c\n", "D\n"]


def test_overlapping_different_edits_conflict():
    ours = ["a\n", "X\n", "c\n", "d\n"]
    theirs = ["a\n", "Y\n", "c\n", "d\n"]

    merged, conflict = _three_way_merge(BASE, ours, theirs)

    assert conflict
    assert merged is None


def test_identical_edits_are_applied_once():
    changed = ["a\n", "X\n", "c\n", "d\n"]

    merged, conflict = _three_way_merge(BASE, changed, changed)

    assert not conflict
    assert merged == changed


def test_only_one_side_changed():
    theirs = ["a\n", "b\n", "c\n", "d\n", "e\n"]

    merged, conflict = _three_way_merge(BASE, BASE, theirs)

    assert not conflict
    assert merged == theirs


def test_inserts_at_the_same_point_with_different_content_conflict():
    ours = ["a\n", "x\n", "b\n", "c\n", "d\n"]
    theirs = ["a\n", "y\n", "b\n", "c\n", "d\n"]

    merged, conflict = _three_way_merge(BASE, ours, theirs)

    assert conflict


def test_edits_overlap_rules():
    assert _edits_overlap((1, 3, ["x"]), (2, 4, ["y"]))
    assert not _edits_overlap((0, 1, ["x"]), (2, 3, ["y"]))
    assert not _edits_overlap((0, 1, ["x"]), (1, 2, ["y"]))
    assert _edits_overlap((2, 2, ["x"]), (2, 2, ["y"]))
    assert _edits_overlap((2, 2, ["x"]), (1, 3, ["y"]))
    assert not _edits_overlap((2, 2, ["x"]), (3, 4, ["y"]))


def test_hand_resolved_conflict_counts_as_applied():
    ours = ["a\n", "X and Y\n", "c\n", "d\n"]
    theirs = ["a\n", "Y\n", "c\n", "d\n"]

    assert not _edits_already_applied(BASE, ours, theirs)

    resolved = ["a\n", "X\n", "Y\n", "c\n", "d\n"]
    assert _edits_already_applied(BASE, resolved, theirs)


def test_unapplied_commit_is_not_reported_applied():
    ours = ["a\n", "X\n", "c\n", "d\n"]
    theirs = ["a\n", "Y\n", "c\n", "d\n"]

    assert not _edits_already_applied(BASE, ours, theirs)


def test_applied_check_ignores_line_endings_and_blank_hunks():
    theirs = ["a\n", "b\n", "c\n", "d\n", "\n"]

    assert not _edits_already_applied(BASE, BASE, theirs)
    assert _edits_already_applied(BASE, ["a\r\n", "Y\r\n", "c\r\n", "d\r\n"], ["a\n", "Y\n", "c\n", "d\n"])


def test_deleted_lines_must_be_gone():
    theirs = ["a\n", "c\n", "d\n"]

    assert not _edits_already_applied(BASE, BASE, theirs)
    assert _edits_already_applied(BASE, ["a\n", "c\n", "d\n"], theirs)


def test_fingerprint_uses_author_email_and_date():
    commit = {"commit": {"author": {"email": "a@b.c", "date": "2026-01-01T00:00:00Z"}}}

    assert _commit_fingerprint(commit) == ("a@b.c", "2026-01-01T00:00:00Z")
    assert _commit_fingerprint({"commit": {}}) is None


def test_compare_combines_every_pr_of_an_environment(monkeypatch):
    from app import helper

    links = {
        "DEV": [
            {"repo": "R", "url": "https://github.com/o/R/pull/2"},
            {"repo": "R", "url": "https://github.com/o/R/pull/1"},
        ],
        "UAT": [{"repo": "R", "url": "https://github.com/o/R/pull/3"}],
        "PROD": [],
    }
    files = {
        1: [{"filename": "a.ts", "sha": "s1"}],
        2: [{"filename": "b.ts", "sha": "s2"}],
        3: [{"filename": "a.ts", "sha": "s1"}, {"filename": "b.ts", "sha": "s2"}],
    }
    monkeypatch.setattr(helper, "get_dev_pr_links", lambda ticket: links["DEV"])
    monkeypatch.setattr(helper, "get_uat_pr_links", lambda ticket: links["UAT"])
    monkeypatch.setattr(helper, "get_prod_pr_links", lambda ticket: links["PROD"])
    monkeypatch.setattr(helper, "get_pr_files", lambda repo, number: files[number])

    report = helper.compare_env_prs("T-1")

    assert report[0]["verdict"] == "MATCH"
    assert report[0]["envs"]["DEV"] == ["https://github.com/o/R/pull/1", "https://github.com/o/R/pull/2"]


def _compare_with_patches(monkeypatch, dev_patches, uat_patch):
    from app import helper

    monkeypatch.setattr(helper, "get_dev_pr_links", lambda ticket: [{"repo": "R", "url": f"https://github.com/o/R/pull/{n}"} for n in dev_patches])
    monkeypatch.setattr(helper, "get_uat_pr_links", lambda ticket: [{"repo": "R", "url": "https://github.com/o/R/pull/9"}])
    monkeypatch.setattr(helper, "get_prod_pr_links", lambda ticket: [])
    patches = {**dev_patches, 9: uat_patch}
    monkeypatch.setattr(
        helper, "get_pr_files", lambda repo, number: [{"filename": "a.ts", "sha": f"sha{number}", "patch": patches[number]}]
    )

    return helper.compare_env_prs("T-1")[0]


def test_compare_ignores_a_different_base_branch(monkeypatch):
    dev = "@@ -1,3 +1,4 @@\n a\n+new line\n b\n c"
    uat = "@@ -10,3 +10,4 @@\n x\n+new line\n y\n z"

    assert _compare_with_patches(monkeypatch, {1: dev}, uat)["verdict"] == "MATCH"


def test_compare_flags_a_changed_line(monkeypatch):
    dev = "@@ -1,2 +1,2 @@\n a\n-old\n+new"
    uat = "@@ -1,2 +1,2 @@\n a\n-old\n+different"

    report = _compare_with_patches(monkeypatch, {1: dev}, uat)

    assert report["verdict"] == "MISMATCH"
    assert report["files"][0]["status"] == "DIFFERS"


def test_compare_nets_a_later_pr_that_removes_an_earlier_line(monkeypatch):
    first = "@@ -1,1 +1,3 @@\n a\n+guard\n+keep"
    second = "@@ -1,3 +1,2 @@\n a\n-guard\n keep"
    uat = "@@ -1,1 +1,2 @@\n a\n+keep"

    assert _compare_with_patches(monkeypatch, {1: first, 2: second}, uat)["verdict"] == "MATCH"


def test_select_prod_sources_prefers_uat_and_falls_back_to_dev():
    from app.helper import select_prod_sources

    dev = [
        {"repo": "A", "url": "https://github.com/o/A/pull/2"},
        {"repo": "A", "url": "https://github.com/o/A/pull/1"},
        {"repo": "B", "url": "https://github.com/o/B/pull/7"},
    ]
    uat = [{"repo": "A", "url": "https://github.com/o/A/pull/9"}, {"repo": "C", "url": "https://github.com/o/C/pull/4"}]

    assert select_prod_sources(dev, uat) == [
        ("A", "UAT", ["https://github.com/o/A/pull/9"]),
        ("B", "DEV", ["https://github.com/o/B/pull/7"]),
        ("C", "UAT", ["https://github.com/o/C/pull/4"]),
    ]
    assert select_prod_sources(dev, uat, "dev") == [
        ("A", "DEV", ["https://github.com/o/A/pull/1", "https://github.com/o/A/pull/2"]),
        ("B", "DEV", ["https://github.com/o/B/pull/7"]),
    ]
    assert select_prod_sources(dev, uat, "uat")[1] == ("B", "UAT", [])


def test_cherry_pick_markers_are_stripped_before_a_new_one_is_added():
    from app.helper import _strip_cherry_pick_markers

    message = "feat: x\n\n(cherry picked from commit abcdef1)\n\n(cherry picked from commit " + "a" * 40 + ")"

    assert _strip_cherry_pick_markers(message) == "feat: x"
    assert _strip_cherry_pick_markers("feat: y") == "feat: y"
