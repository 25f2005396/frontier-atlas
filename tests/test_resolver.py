import pytest

from src.resolver.resolver import EntityResolver, normalize


@pytest.fixture(scope="module")
def resolver():
    return EntityResolver()


@pytest.mark.parametrize("raw", ["OpenAI", "OpenAI, Inc.", "Open AI", "openai", "  OPENAI  ", "The OpenAI Inc"])
def test_openai_variants(resolver, raw):
    assert resolver.resolve(raw).canonical == "OpenAI"


@pytest.mark.parametrize("raw,expected", [
    ("Hugging Face Inc.", "Hugging Face"),
    ("HuggingFace", "Hugging Face"),
    ("Weights and Biases", "Weights & Biases"),
    ("x.ai", "xAI"),
    ("Cursor", "Anysphere"),
    ("DeepMind", "Google DeepMind"),
    ("Anthropc", "Anthropic"),        # typo: should resolve via fuzzy
])
def test_known_variants(resolver, raw, expected):
    assert resolver.resolve(raw).canonical == expected


@pytest.mark.parametrize("raw", ["Totally Unknown Startup", "Lambda School", "Pikachu", ""])
def test_unknown_is_not_guessed(resolver, raw):
    assert resolver.resolve(raw).canonical is None


def test_normalize():
    assert normalize("OpenAI, Inc.") == normalize("Open AI") == "openai"