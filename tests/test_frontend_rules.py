"""Guard: the frontend follows the skill's mechanical rules.

`.agents/skills/book-companion-ui/SKILL.md` is the taste authority and its
"Repo bindings" override taste; this test makes the checkable half fail the
suite instead of relying on a reviewer's eye (the same move as
`test_generalization.py`, aimed at `web/`).

Literal by design — it pins: no colour literals outside `tokens.css`, no raw
shadows (the one floating control uses `var(--lens-shadow)`), no monospace, no
emoji, every literal class name has a rule in the app's stylesheets, and the
dependency list is the approved stack. The engine stays stdlib.
"""

import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
TOKENS = WEB / "app" / "tokens.css"

# The only stylesheets and component sources an agent may touch.
SOURCE_DIRS = (WEB / "app", WEB / "components", WEB / "lib")

HEX = re.compile(r"#[0-9a-fA-F]{3,8}\b")
RGB = re.compile(r"\brgba?\(")
MONO = re.compile(r"monospace|font-mono")
# Pictographs and the variation selector only: the typographic marks the app
# uses (✕, ×, —) are not emoji.
EMOJI = re.compile("[\U0001F000-\U0001FAFF\uFE0F]")
CLASSNAME = re.compile(r'className="([^"{]+)"')
ALLOWED_DEPS = {"next", "react", "react-dom", "zustand"}
ALLOWED_DEV_DEPS = {
    "@tailwindcss/postcss", "@types/node", "@types/react", "@types/react-dom",
    "tailwindcss", "typescript",
}


def source_files(suffixes):
    for folder in SOURCE_DIRS:
        if not folder.is_dir():
            continue
        for path in sorted(folder.rglob("*")):
            if path.suffix in suffixes and path.is_file():
                yield path


def hits(pattern, paths, skip=()):
    """(path, line number, line) for every match, tokens.css skipped."""
    found = []
    for path in paths:
        if path in skip:
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if pattern.search(line):
                found.append((path, number, line.strip()))
    return found


class FrontendRulesTest(unittest.TestCase):
    def test_no_colour_literals_outside_the_tokens(self):
        """Every colour lives in tokens.css; components and rules use var()."""
        for pattern, label in ((HEX, "hex colour"), (RGB, "rgb() colour")):
            for path, number, line in hits(
                pattern, source_files({".css", ".tsx", ".ts"}), skip=(TOKENS,)
            ):
                self.fail(
                    f"{path.relative_to(ROOT)}:{number} holds a {label}: {line[:70]!r}"
                )

    def test_shadows_stay_behind_the_lens_token(self):
        """No raw shadow values: the floating pill is the one allowed shadow."""
        for path, number, line in hits(
            re.compile(r"box-shadow"), source_files({".css"}), skip=(TOKENS,)
        ):
            if "var(" not in line:
                self.fail(
                    f"{path.relative_to(ROOT)}:{number} writes a raw shadow: {line[:70]!r}"
                )

    def test_no_monospace(self):
        for path, number, line in hits(MONO, source_files({".css", ".tsx", ".ts"})):
            self.fail(f"{path.relative_to(ROOT)}:{number} uses monospace: {line[:70]!r}")

    def test_no_emoji(self):
        for path, number, line in hits(
            EMOJI, source_files({".css", ".tsx", ".ts"})
        ):
            self.fail(f"{path.relative_to(ROOT)}:{number} holds an emoji: {line[:70]!r}")

    def test_every_literal_class_name_has_a_rule(self):
        """A class the components use must exist in the app's stylesheets —
        this is what catches Tailwind utilities and orphan class names."""
        css = "\n".join(
            path.read_text(encoding="utf-8") for path in source_files({".css"})
        )
        missing = []
        for path in source_files({".tsx"}):
            for number, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), 1
            ):
                for classes in CLASSNAME.findall(line):
                    for name in classes.split():
                        if f".{name}" not in css:
                            missing.append(f"{path.relative_to(ROOT)}:{number} .{name}")
        self.assertEqual(missing, [], f"class names without a CSS rule: {missing}")

    def test_only_the_approved_dependencies(self):
        package = json.loads((WEB / "package.json").read_text(encoding="utf-8"))
        self.assertEqual(set(package.get("dependencies", {})), ALLOWED_DEPS)
        self.assertEqual(set(package.get("devDependencies", {})), ALLOWED_DEV_DEPS)


if __name__ == "__main__":
    unittest.main()
