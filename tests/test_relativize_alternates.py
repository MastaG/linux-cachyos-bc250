import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "relativize-git-alternates.sh"


def git(*args, cwd=None):
    env = dict(os.environ, GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_SYSTEM="/dev/null",
               GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t",
               GIT_COMMITTER_EMAIL="t@t")
    return subprocess.run(["git", *args], cwd=cwd, env=env, capture_output=True, text=True)


@unittest.skipUnless(shutil.which("git"), "needs git")
class RelativizeAlternatesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        work = self.tmp / "work"
        work.mkdir()
        git("init", "-q", cwd=work)
        (work / "f").write_text("one\n")
        git("add", "f", cwd=work)
        git("commit", "-q", "-m", "one", cwd=work)
        self.build = self.tmp / "build"
        pkg = self.build / "pkg"
        (pkg / "src").mkdir(parents=True)
        self.mirror = pkg / "mirror"
        git("clone", "-q", "--bare", str(work), str(self.mirror))
        self.clone = pkg / "src" / "mirror"
        git("clone", "-q", "--shared", str(self.mirror), str(self.clone))
        self.alternates = self.clone / ".git" / "objects" / "info" / "alternates"

    def run_script(self, root):
        return subprocess.run(["bash", str(SCRIPT), str(root)], capture_output=True, text=True)

    def test_the_setup_really_stores_an_absolute_path(self):
        self.assertTrue(self.alternates.read_text().startswith("/"))

    def test_a_clone_still_works_after_the_tree_is_moved(self):
        self.assertEqual(self.run_script(self.build).returncode, 0)
        self.assertFalse(self.alternates.read_text().startswith("/"))
        moved = self.tmp / "elsewhere"
        self.build.rename(moved)
        clone = moved / "pkg" / "src" / "mirror"
        self.assertEqual(git("log", "-1", "--format=%s", cwd=clone).stdout.strip(), "one")
        (clone / "f").write_text("two\n")
        self.assertIn("+two", git("diff", cwd=clone).stdout)

    def test_the_absolute_path_is_what_breaks_without_it(self):
        moved = self.tmp / "elsewhere"
        self.build.rename(moved)
        clone = moved / "pkg" / "src" / "mirror"
        self.assertNotEqual(git("log", "-1", cwd=clone).returncode, 0)

    def test_running_it_twice_changes_nothing(self):
        self.run_script(self.build)
        first = self.alternates.read_text()
        self.run_script(self.build)
        self.assertEqual(self.alternates.read_text(), first)

    def test_a_path_that_does_not_exist_is_left_alone(self):
        self.alternates.write_text("/nonexistent/objects\n")
        self.assertEqual(self.run_script(self.build).returncode, 0)
        self.assertEqual(self.alternates.read_text(), "/nonexistent/objects\n")

    def test_a_tree_without_clones_is_fine(self):
        empty = self.tmp / "empty"
        empty.mkdir()
        self.assertEqual(self.run_script(empty).returncode, 0)


if __name__ == "__main__":
    unittest.main()
