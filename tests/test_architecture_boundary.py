from pathlib import Path

CORE_ROOT = Path(__file__).parents[1] / "src" / "worldstate"

FORBIDDEN_IMPORT_MARKERS = (
    "import geotask",
    "from geotask",
    "import agentreality",
    "from agentreality",
    "import lowa",
    "from lowa",
    "import deepseek",
    "from deepseek",
    "import gstar",
    "from gstar",
)

FORBIDDEN_DOMAIN_VOCABULARY = (
    "airport",
    "aviation",
    "facility",
    "fss",
    "telecom",
)


def _core_python_text() -> str:
    return "\n".join(
        path.read_text(encoding="utf-8").lower()
        for path in sorted(CORE_ROOT.glob("*.py"))
    )


def test_core_has_no_stack_or_domain_import_dependency() -> None:
    text = _core_python_text()
    for marker in FORBIDDEN_IMPORT_MARKERS:
        assert marker not in text


def test_core_has_no_domain_vocabulary_leak() -> None:
    text = _core_python_text()
    for token in FORBIDDEN_DOMAIN_VOCABULARY:
        assert token not in text
