"""Which analyser each test describes.

Most of this suite was written when UniDic was the only engine, so its
assertions record UNIDIC's decisions: where it draws word boundaries, which
readings its lexicon carries, how the phrase list patches its gaps. Those are
still worth pinning -- UniDic remains selectable and remains the fallback for
anything the dictionary does not cover -- but they are statements about one
engine, not about the tool.

So the default here is `unidic`, and tests for the dictionary path opt in
explicitly. That is the opposite of the shipped default, deliberately: a test
should say which engine it is talking about rather than inherit whichever one
happens to be current, or every future change of default silently rewrites what
the suite is asserting.
"""
import pytest

from aksal import readings


@pytest.fixture(autouse=True)
def analyser_engine(request):
    """Select the engine for each test; `ichiran` via the marker."""
    marker = request.node.get_closest_marker("ichiran")
    previous = readings.ENGINE
    readings.set_engine("ichiran" if marker else "unidic")
    yield
    readings.ENGINE = previous


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "ichiran: exercise the JMdict/ichiran analyser")
