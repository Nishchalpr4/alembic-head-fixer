import json

from alembic_head_fixer.cli import main
from alembic_head_fixer.fix import rewrite_source
from alembic_head_fixer.graph import load_dir, parse_migration


def chain(repo):
    """{revision: (parents, filename)} of what is on disk now."""
    migrations, errors = load_dir(repo.versions)
    assert errors == []
    return {m.revision: (m.parents, m.name) for m in migrations}


def race(repo):
    """main at 001 (applied); two PRs each add 002 on top of 001; both merge."""
    repo.migration("001", None, "users")
    repo.commit("001")
    repo.mark_applied()
    repo.pr("invoices", ("002", "001", "invoices"))
    repo.pr("coupons", ("002", "001", "coupons"))
    repo.merge("invoices")
    repo.merge("coupons")


def test_healthy_history_is_left_alone(repo, capsys):
    repo.migration("001", None, "users")
    repo.commit("001")
    assert main(["fix", "--applied-ref", "does-not-even-matter"]) == 0
    assert "nothing to fix" in capsys.readouterr().out


def test_the_later_merge_moves_onto_the_earlier_one(repo):
    race(repo)
    invoices_before = (repo.versions / "002_invoices.py").read_bytes()

    assert main(["fix", "--applied-ref", "applied"]) == 0

    assert repo.files() == ["001_users.py", "002_invoices.py", "003_coupons.py"]
    assert chain(repo)["003"] == (("002",), "003_coupons.py")
    assert (repo.versions / "002_invoices.py").read_bytes() == invoices_before
    assert main(["check"]) == 0


def test_merge_order_decides_not_file_names(repo):
    repo.migration("001", None, "users")
    repo.commit("001")
    repo.mark_applied()
    repo.pr("invoices", ("002", "001", "invoices"))
    repo.pr("coupons", ("002", "001", "coupons"))
    repo.merge("coupons")
    repo.merge("invoices")

    assert main(["fix", "--applied-ref", "applied"]) == 0
    assert repo.files() == ["001_users.py", "002_coupons.py", "003_invoices.py"]


def test_a_migration_that_already_ran_is_never_moved(repo):
    """coupons merged first, but the database ran invoices (deployed from another branch).
    What ran stays put, even though git's merge order says otherwise."""
    repo.migration("001", None, "users")
    repo.commit("001")
    repo.pr("invoices", ("002", "001", "invoices"))
    repo.pr("coupons", ("002", "001", "coupons"))
    repo.merge("coupons")
    repo.git("checkout", "-q", "-b", "deployed", "main~1")
    repo.merge("invoices")
    repo.mark_applied()
    repo.git("checkout", "-q", "main")
    repo.merge("invoices")
    applied_before = (repo.versions / "002_invoices.py").read_bytes()

    assert main(["fix", "--applied-ref", "applied"]) == 0

    assert (repo.versions / "002_invoices.py").read_bytes() == applied_before
    assert chain(repo)["003"] == (("002",), "003_coupons.py")


def test_stale_branch_point_is_replayed_on_the_head(repo):
    """A PR written against 001 lands after 002 and 003 already ran: it must run after them."""
    repo.migration("001", None, "users")
    repo.commit("001")
    repo.pr("old-pr", ("004", "001", "late"))
    repo.migration("002", "001", "orders")
    repo.migration("003", "002", "payments")
    repo.commit("002 003")
    repo.mark_applied()
    repo.merge("old-pr")

    assert main(["fix", "--applied-ref", "applied"]) == 0
    assert chain(repo)["004"] == (("003",), "004_late.py")


def test_a_stack_from_one_pr_moves_together(repo):
    race(repo)
    repo.pr("stack", ("002", "001", "x"), ("003", "002", "x"))
    repo.merge("stack")

    assert main(["fix", "--applied-ref", "applied"]) == 0

    graph = chain(repo)
    assert graph["003"] == (("002",), "003_coupons.py")
    assert graph["004"] == (("003",), "004_x.py")
    assert graph["005"] == (("004",), "005_x.py")
    assert main(["check"]) == 0


def test_a_move_can_take_the_name_another_move_vacates(repo):
    repo.migration("001", None, "users")
    repo.commit("001")
    repo.mark_applied()
    repo.pr("invoices", ("002", "001", "invoices"))
    repo.pr("stack", ("002", "001", "x"), ("003", "002", "x"))
    repo.merge("invoices")
    repo.merge("stack")

    assert main(["fix", "--applied-ref", "applied"]) == 0

    assert repo.files() == ["001_users.py", "002_invoices.py", "003_x.py", "004_x.py"]
    assert chain(repo)["004"] == (("003",), "004_x.py")
    assert not list(repo.versions.glob(".*.tmp"))


def test_zero_padding_survives(repo):
    repo.migration("0041", None, "users")
    repo.commit("0041")
    repo.mark_applied()
    repo.pr("a", ("0042", "0041", "a"))
    repo.pr("b", ("0042", "0041", "b"))
    repo.merge("a")
    repo.merge("b")

    assert main(["fix", "--applied-ref", "applied"]) == 0
    assert "0043_b.py" in repo.files()


def test_personal_code_ids_keep_their_name(repo):
    repo.migration("001", None, "users")
    repo.commit("001")
    repo.mark_applied()
    repo.pr("alice", ("alice_01", "001", "a"))
    repo.pr("bob", ("bob_01", "001", "b"))
    repo.merge("alice")
    repo.merge("bob")

    assert main(["fix", "--applied-ref", "applied"]) == 0
    assert chain(repo)["bob_01"] == (("alice_01",), "bob_01_b.py")


def test_clashing_non_numeric_ids_get_a_suffix(repo):
    repo.migration("001", None, "users")
    repo.commit("001")
    repo.mark_applied()
    repo.pr("a", ("alice_01", "001", "a"))
    repo.pr("b", ("alice_01", "001", "b"))
    repo.merge("a")
    repo.merge("b")

    assert main(["fix", "--applied-ref", "applied"]) == 0
    assert chain(repo)["alice_01_2"] == (("alice_01",), "alice_01_2_b.py")


def test_refuses_when_the_applied_history_itself_is_forked(repo, capsys):
    race(repo)
    repo.mark_applied()  # claims both 002s ran: impossible to fix without rewriting one
    before = {p.name: p.read_bytes() for p in repo.versions.glob("*.py")}

    assert main(["fix", "--applied-ref", "applied"]) == 1

    assert "already ran" in capsys.readouterr().err
    assert {p.name: p.read_bytes() for p in repo.versions.glob("*.py")} == before


def test_refuses_without_an_applied_ref(repo, capsys):
    race(repo)
    repo.git("tag", "-d", "applied")
    assert main(["fix", "--applied-ref", "applied"]) == 1
    assert "no record of which migrations" in capsys.readouterr().err
    assert "002_coupons.py" in repo.files()


def test_dry_run_writes_nothing(repo, capsys):
    race(repo)
    assert main(["fix", "--applied-ref", "applied", "--dry-run"]) == 0
    assert "Would re-chain" in capsys.readouterr().out
    assert "002_coupons.py" in repo.files()


def test_report(repo, tmp_path):
    race(repo)
    report = tmp_path / "report.json"
    assert main(["fix", "--applied-ref", "applied", "--report", str(report)]) == 0

    (entry,) = json.loads(report.read_text())
    assert entry == {
        "commit": repo.git("rev-parse", "HEAD"),
        "file": "alembic/versions/002_coupons.py",
        "new_file": "alembic/versions/003_coupons.py",
        "revision": "002",
        "new_revision": "003",
        "down_revision": ["001"],
        "new_down_revision": ["002"],
    }


def test_rewrite_keeps_quotes_line_endings_and_docstring_honest(repo):
    path = repo.migration("002", "001", "coupons", quote='"', newline="\r\n")
    updated = rewrite_source(path.read_bytes(), path.name, "003", ("002",))

    assert b'revision: str = "003"\r\n' in updated
    assert b'down_revision: Union[str, None] = "002"\r\n' in updated
    assert b"Revision ID: 003\r\n" in updated
    assert b"Revises: 002\r\n" in updated
    assert b"\n" not in updated.replace(b"\r\n", b"")
    parsed = parse_migration(updated.decode(), path)
    assert (parsed.revision, parsed.parents) == ("003", ("002",))
