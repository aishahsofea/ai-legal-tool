import io
import os
import re
import unittest
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parent.parent
BACKEND_TEMPLATE = ROOT / ".env.example"
FRONTEND_TEMPLATE = ROOT / "frontend" / ".env.example"

_READ = re.compile(
    r"""(?:os\.getenv|os\.environ\.get|flag_enabled)\(\s*["']([A-Z][A-Z0-9_]*)["']"""
    r"""|os\.environ\[\s*["']([A-Z][A-Z0-9_]*)["']\s*\]"""
)
_READ_WITH_DEFAULT = re.compile(r"""(?:os\.getenv|os\.environ\.get)\(\s*["']([A-Z][A-Z0-9_]*)["']\s*,""")
_FRONTEND_READ = re.compile(r"process\.env\.([A-Z][A-Z0-9_]*)")
# Commented-out lines count: an optional variable is listed, just not set.
_TEMPLATE_NAME = re.compile(r"^#?[ \t]*([A-Z][A-Z0-9_]*)=", re.MULTILINE)

# The OpenAI, Anthropic, Google, and LangSmith SDKs read these themselves, so no
# os.getenv in this repo names them.
_READ_BY_SDKS = {
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "GOOGLE_API_KEY",
    "LANGSMITH_TRACING",
    "LANGSMITH_API_KEY",
    "LANGSMITH_PROJECT",
}


def _backend_sources():
    # Top-level packages only, so a virtualenv or data directory in the checkout
    # can't add names the app never reads.
    yield from ROOT.glob("*.py")
    for package in ROOT.iterdir():
        if package.name != "tests" and (package / "__init__.py").is_file():
            yield from package.rglob("*.py")


def _frontend_sources():
    for directory, subdirs, files in os.walk(ROOT / "frontend"):
        subdirs[:] = [d for d in subdirs if d != "node_modules" and not d.startswith(".")]
        for name in files:
            if name.endswith((".ts", ".tsx")):
                yield Path(directory, name)


def _template_names(path: Path) -> set[str]:
    return set(_TEMPLATE_NAME.findall(path.read_text()))


class EnvExampleTests(unittest.TestCase):
    def test_backend_template_names_every_variable_the_code_reads(self):
        read = set()
        for path in _backend_sources():
            read |= {name for pair in _READ.findall(path.read_text()) for name in pair if name}
        self.assertIn("DATABASE_URL", read, "the scan found nothing; check _READ")

        missing = (read | _READ_BY_SDKS) - _template_names(BACKEND_TEMPLATE)
        self.assertFalse(missing, f"add these to .env.example: {sorted(missing)}")

    def test_frontend_template_names_every_variable_the_frontend_reads(self):
        read = set()
        for path in _frontend_sources():
            read |= set(_FRONTEND_READ.findall(path.read_text()))
        self.assertIn("NEXT_PUBLIC_API_URL", read, "the scan found nothing; check _FRONTEND_READ")

        missing = read - _template_names(FRONTEND_TEMPLATE)
        self.assertFalse(missing, f"add these to frontend/.env.example: {sorted(missing)}")

    def test_no_live_blank_line_hides_a_code_default(self):
        # python-dotenv loads `NAME=` as "", and os.getenv(NAME, default) then returns
        # "" instead of the default. int("") at import stops the API from starting.
        defaulted = set()
        for path in _backend_sources():
            defaulted |= set(_READ_WITH_DEFAULT.findall(path.read_text()))
        # Read the text first: dotenv_values on a missing path returns {} and would pass.
        values = dotenv_values(stream=io.StringIO(BACKEND_TEMPLATE.read_text()))
        blank = {name for name, value in values.items() if not value}

        self.assertFalse(
            blank & defaulted,
            f"comment these out in .env.example instead of leaving them blank: {sorted(blank & defaulted)}",
        )


if __name__ == "__main__":
    unittest.main()
