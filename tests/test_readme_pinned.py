#!/usr/bin/env python3
"""The README's install clone is pinned to the released tag (friction #5).

`git clone https://github.com/lipi4242/anytime-engine` took the default branch: a 0.3.0
brain got whatever main held that day. The quickstart clones `--branch v<version>`, and
that version is the code's (`anytime_engine.__version__`, which release.sh requires to equal
release.json at release time), so a version bump must move the README too. Reading the code
version (not release.json) lets the version-only PR and the release.json/CHANGELOG PR land in
separate lanes without a red main in between.
Compatible with pytest and direct execution (stdlib unittest).
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

REL = Path(__file__).resolve().parent.parent


class TestReadmePinned(unittest.TestCase):
    def test_every_install_clone_names_the_release_tag(self):
        init = REL / "src" / "anytime_engine" / "__init__.py"
        if not ((REL / "release.json").is_file() and (REL / "README.md").is_file() and init.is_file()):
            self.skipTest("an installed engine (sync-to.sh) carries no release.json / README.md")
        version = re.search(r'^__version__ = "([^"]+)"', init.read_text(encoding="utf-8"), re.M).group(1)
        text = (REL / "README.md").read_text(encoding="utf-8")
        clones = re.findall(r"git clone [^\n]*anytime-engine /tmp/anytime-engine", text)
        self.assertTrue(clones)
        for c in clones:
            self.assertIn("--branch v%s " % version, c, c)


if __name__ == "__main__":
    unittest.main()
