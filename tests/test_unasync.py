import copy
import errno
import io
import os

try:
    import pathlib
except ImportError:
    import pathlib2 as pathlib
import shutil
import subprocess
import sys

import pytest

import unasync

TEST_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
ASYNC_DIR = os.path.join(TEST_DIR, "async")
SYNC_DIR = os.path.join(TEST_DIR, "sync")
TEST_FILES = sorted([f for f in os.listdir(ASYNC_DIR) if f.endswith(".py")])

if sys.version_info[0] == 2:
    TEST_FILES.remove("typing_py3.py")


def list_files(startpath):
    output = ""
    for root, dirs, files in os.walk(startpath):
        # Ensure that we do not capture the directory inode order on
        # platforms that don't pre-sort `readdir` results
        dirs.sort()
        files.sort()

        level = root.replace(startpath, "").count(os.sep)
        indent = " " * 4 * (level)
        output += "{}{}/".format(indent, os.path.basename(root))
        output += "\n"
        subindent = " " * 4 * (level + 1)
        for f in files:
            output += "{}{}".format(subindent, f)
            output += "\n"
    return output


def test_rule_on_short_path():
    rule = unasync.Rule("/ahip/tests/", "/hip/tests/")
    assert rule._match("/ahip/") is False


def test_rule_with_pathlib_path():
    path_async_base = pathlib.Path("/ahip")
    path_sync_base = pathlib.Path("/hip")
    unasync.Rule(path_async_base / "tests", path_sync_base / "tests")


@pytest.mark.parametrize("source_file", TEST_FILES)
def test_unasync(tmpdir, source_file):

    rule = unasync.Rule(fromdir=ASYNC_DIR, todir=str(tmpdir))
    rule._unasync_file(os.path.join(ASYNC_DIR, source_file))

    encoding = "latin-1" if "encoding" in source_file else "utf-8"
    with io.open(os.path.join(SYNC_DIR, source_file), encoding=encoding) as f:
        truth = f.read()
    with io.open(os.path.join(str(tmpdir), source_file), encoding=encoding) as f:
        unasynced_code = f.read()
        assert unasynced_code == truth


def test_unasync_files(tmpdir):
    """Test the unasync_files API, not tied by a Rule or to setuptools."""
    unasync.unasync_files(
        [os.path.join(ASYNC_DIR, fpath) for fpath in TEST_FILES],
        rules=[unasync.Rule(fromdir=ASYNC_DIR, todir=str(tmpdir))],
    )

    for source_file in TEST_FILES:
        encoding = "latin-1" if "encoding" in source_file else "utf-8"
        with io.open(os.path.join(SYNC_DIR, source_file), encoding=encoding) as f:
            truth = f.read()
        with io.open(os.path.join(str(tmpdir), source_file), encoding=encoding) as f:
            unasynced_code = f.read()
            assert unasynced_code == truth


def test_build_py_modules(tmpdir):

    source_modules_dir = os.path.join(TEST_DIR, "example_mod")
    mod_dir = str(tmpdir) + "/" + "example_mod"
    shutil.copytree(source_modules_dir, mod_dir)

    env = copy.copy(os.environ)
    env["PYTHONPATH"] = os.path.realpath(os.path.join(TEST_DIR, ".."))
    subprocess.check_call([sys.executable, "setup.py", "build"], cwd=mod_dir, env=env)
    # Calling it twice to test the "if not copied" branch
    subprocess.check_call([sys.executable, "setup.py", "build"], cwd=mod_dir, env=env)

    unasynced = os.path.join(mod_dir, "build/lib/_sync/some_file.py")
    tree_build_dir = list_files(mod_dir)

    with open(unasynced) as f:
        unasynced_code = f.read()
        assert unasynced_code == "def f():\n    return 1\n"


def test_build_py_packages(tmpdir):

    source_pkg_dir = os.path.join(TEST_DIR, "example_pkg")
    pkg_dir = str(tmpdir) + "/" + "example_pkg"
    shutil.copytree(source_pkg_dir, pkg_dir)

    env = copy.copy(os.environ)
    env["PYTHONPATH"] = os.path.realpath(os.path.join(TEST_DIR, ".."))
    subprocess.check_call([sys.executable, "setup.py", "build"], cwd=pkg_dir, env=env)

    unasynced = os.path.join(pkg_dir, "build/lib/example_pkg/_sync/__init__.py")

    with open(unasynced) as f:
        unasynced_code = f.read()
        assert unasynced_code == "def f():\n    return 1\n"


def test_project_structure_after_build_py_packages(tmpdir):

    source_pkg_dir = os.path.join(TEST_DIR, "example_pkg")
    pkg_dir = str(tmpdir) + "/" + "example_pkg"
    shutil.copytree(source_pkg_dir, pkg_dir)

    env = copy.copy(os.environ)
    env["PYTHONPATH"] = os.path.realpath(os.path.join(TEST_DIR, ".."))
    subprocess.check_call([sys.executable, "setup.py", "build"], cwd=pkg_dir, env=env)

    _async_dir_tree = list_files(
        os.path.join(source_pkg_dir, "src/example_pkg/_async/.")
    )
    unasynced_dir_tree = list_files(
        os.path.join(pkg_dir, "build/lib/example_pkg/_sync/.")
    )

    assert _async_dir_tree == unasynced_dir_tree


def test_project_structure_after_customized_build_py_packages(tmpdir):

    source_pkg_dir = os.path.join(TEST_DIR, "example_custom_pkg")
    pkg_dir = str(tmpdir) + "/" + "example_custom_pkg"
    shutil.copytree(source_pkg_dir, pkg_dir)

    env = copy.copy(os.environ)
    env["PYTHONPATH"] = os.path.realpath(os.path.join(TEST_DIR, ".."))
    subprocess.check_call([sys.executable, "setup.py", "build"], cwd=pkg_dir, env=env)

    _async_dir_tree = list_files(os.path.join(source_pkg_dir, "src/ahip/."))
    unasynced_dir_path = os.path.join(pkg_dir, "build/lib/hip/.")
    unasynced_dir_tree = list_files(unasynced_dir_path)

    assert _async_dir_tree == unasynced_dir_tree

    with open(os.path.join(unasynced_dir_path, "tests/test_conn.py")) as f:
        assert "import hip\n" in f.read()


def test_makedirs_existok(monkeypatch):
    def raises(*args, **kwargs):
        # Unexpected OSError
        raise OSError(errno.EPERM, "Operation not permitted")

    monkeypatch.setattr(os, "makedirs", raises)
    with pytest.raises(OSError):
        unasync._makedirs_existok("path")
