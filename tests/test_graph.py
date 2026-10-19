from pathlib import Path

import pytest

from alembic_head_fixer.graph import Migration, MigrationParseError, find_problems, heads, parse_migration


def m(revision, *parents):
    return Migration(Path(f"{revision}_x.py"), revision, tuple(parents))


def test_parses_plain_and_annotated_assignments():
    plain = parse_migration('revision = "a1"\ndown_revision = None\n', Path("a1.py"))
    annotated = parse_migration("revision: str = 'b2'\ndown_revision: Union[str, None] = 'a1'\n", Path("b2.py"))
    assert (plain.revision, plain.parents) == ("a1", ())
    assert (annotated.revision, annotated.parents) == ("b2", ("a1",))


def test_parses_merge_revision_tuple():
    merge = parse_migration("revision = 'm'\ndown_revision = ('a', 'b')\n", Path("m.py"))
    assert merge.parents == ("a", "b")


def test_never_executes_the_file():
    source = "import does_not_exist\nraise SystemExit(1)\nrevision = 'a'\ndown_revision = None\n"
    assert parse_migration(source, Path("a.py")).revision == "a"


@pytest.mark.parametrize("source", ["down_revision = None\n", "revision = make_id()\n", "revision = 'a'\ndef (:\n"])
def test_unreadable_files_raise(source):
    with pytest.raises(MigrationParseError):
        parse_migration(source, Path("bad.py"))


def test_single_chain_has_no_problems():
    graph = [m("1"), m("2", "1"), m("3", "2")]
    assert heads(graph) == ["3"]
    assert find_problems(graph) == []


def test_merge_revision_closes_a_fork():
    assert find_problems([m("1"), m("2a", "1"), m("2b", "1"), m("3", "2a", "2b")]) == []


def test_fork_reports_both_heads_and_where_it_forked():
    (problem,) = find_problems([m("1"), m("2a", "1"), m("2b", "1")])
    assert "2 heads: 2a, 2b" in problem
    assert "1 -> 2a_x.py, 2b_x.py" in problem


def test_duplicate_and_unknown_ids():
    problems = find_problems([m("1"), m("2", "1"), Migration(Path("2_other.py"), "2", ("1",)), m("3", "9")])
    assert any("duplicate revision id '2'" in p for p in problems)
    assert any("do not exist: 9" in p for p in problems)


def test_id_length_only_checked_when_asked():
    graph = [m("x" * 33)]
    assert find_problems(graph) == []
    assert "33 characters" in find_problems(graph, max_id_length=32)[0]
