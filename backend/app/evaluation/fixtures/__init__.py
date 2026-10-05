"""Ground-truth fixture repositories for evaluation (task 11.1).

Each builder creates a small, deterministic git repo whose architecture,
ownership, and dependency characteristics are known, so metrics can be computed
against exact expectations. These stand in for real open-source repos to keep
evaluation offline and reproducible; real repos can be added later via the
ingestion path without changing the metric code.
"""

from __future__ import annotations

from pathlib import Path

from git import Actor, Repo

ALICE = Actor("Alice", "alice@example.com")
BOB = Actor("Bob", "bob@example.com")


def _commit(repo: Repo, rel: str, content: str, author: Actor, msg: str):
    path = Path(repo.working_tree_dir) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    repo.index.add([rel])
    repo.index.commit(msg, author=author, committer=author)


def build_layered_app(root: Path) -> Path:
    """A layered app: web -> service -> repository -> db, with a shared utils.

    Alice dominates service.py (bus-factor). requirements.txt pins a dep.
    """
    repo = Repo.init(root)
    _commit(repo, "requirements.txt", "requests==2.31.0\n", ALICE, "deps")
    _commit(repo, "app/__init__.py", "", ALICE, "pkg")
    _commit(repo, "app/utils.py", "def fmt(x):\n    return str(x)\n", ALICE, "utils")
    _commit(repo, "app/db.py", "from app import utils\n\n\ndef connect():\n    return utils.fmt('db')\n", BOB, "db")
    _commit(repo, "app/repository.py",
            "from app import db\n\n\ndef get(id):\n    return db.connect()\n", ALICE, "repo")
    # Alice makes service.py hers (4 commits).
    for i in range(4):
        _commit(repo, "app/service.py",
                f"from app import repository\n\n\ndef handle(id={i}):\n    return repository.get(id)\n",
                ALICE, f"service {i}")
    _commit(repo, "app/web.py",
            "from app import service\n\n\ndef route(id):\n    return service.handle(id)\n", BOB, "web")
    repo.close()
    return root


def build_tested_lib(root: Path) -> Path:
    """A small library with a tests/ dir (so coverage would apply) and no deps."""
    repo = Repo.init(root)
    _commit(repo, "lib/__init__.py", "", ALICE, "pkg")
    _commit(repo, "lib/core.py", "def add(a, b):\n    return a + b\n", ALICE, "core")
    _commit(repo, "lib/mathx.py",
            "from lib import core\n\n\ndef double(x):\n    return core.add(x, x)\n", ALICE, "mathx")
    _commit(repo, "tests/test_core.py",
            "from lib import core\n\n\ndef test_add():\n    assert core.add(1, 2) == 3\n", ALICE, "tests")
    repo.close()
    return root


BUILDERS = {
    "layered_app": build_layered_app,
    "tested_lib": build_tested_lib,
}


def build_fixture(name: str, root: Path) -> Path:
    builder = BUILDERS[name]
    path = builder(root)
    return path