from alembic_head_fixer.cli import main


def test_single_head_passes(repo, capsys):
    repo.migration("001", None, "users")
    repo.migration("002", "001", "orders")
    assert main(["check"]) == 0
    assert "single head '002'" in capsys.readouterr().out


def test_two_prs_on_the_same_parent_fail(repo, capsys):
    repo.migration("001", None, "users")
    repo.migration("002", "001", "invoices")
    repo.migration("003", "001", "coupons")
    assert main(["check"]) == 1
    assert "2 heads: 002, 003" in capsys.readouterr().err


def test_long_revision_id_fails(repo, capsys):
    repo.migration("alice_01_add_a_really_long_descriptive_slug", None, "x")
    assert main(["check"]) == 1
    assert "alembic_version.version_num only holds 32" in capsys.readouterr().err


def test_github_annotations(repo, capsys, monkeypatch):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    repo.migration("001", None, "a")
    repo.migration("002", None, "b")
    assert main(["check"]) == 1
    assert capsys.readouterr().err.startswith("::error::")


def test_base_ref_catches_a_taken_id(repo, capsys):
    repo.migration("001", None, "users")
    repo.commit("001")
    repo.pr("feature", ("002", "001", "coupons"))
    repo.migration("002", "001", "invoices")  # someone else merges first
    repo.commit("002 invoices")

    repo.git("checkout", "-q", "feature")
    assert main(["check", "--base-ref", "main"]) == 1
    assert "002_coupons.py: revision id '002' is already taken on main by 002_invoices.py" in capsys.readouterr().err


def test_base_ref_catches_a_stale_branch_point(repo, capsys):
    repo.migration("001", None, "users")
    repo.commit("001")
    repo.pr("feature", ("003", "001", "coupons"))
    repo.migration("002", "001", "invoices")
    repo.commit("002 invoices")

    repo.git("checkout", "-q", "feature")
    assert main(["check", "--base-ref", "main"]) == 1
    assert "003_coupons.py: down_revision is '001', but main's head is now '002'" in capsys.readouterr().err


def test_base_ref_accepts_a_stack_that_attaches_at_the_head(repo):
    repo.migration("001", None, "users")
    repo.commit("001")
    repo.pr("feature", ("002", "001", "a"), ("003", "002", "b"), ("004", "003", "c"))
    repo.git("checkout", "-q", "feature")
    assert main(["check", "--base-ref", "main"]) == 0


def test_base_ref_that_does_not_exist(repo, capsys):
    repo.migration("001", None, "users")
    repo.commit("001")
    assert main(["check", "--base-ref", "origin/nope"]) == 1
    assert "not found" in capsys.readouterr().err
