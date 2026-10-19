from app.helper import _edits_overlap, _three_way_merge

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
