import pathlib


def test_config_does_not_import_searcher():
    src = pathlib.Path("src/config/__init__.py").read_text(encoding="utf-8")
    assert "src.searcher" not in src and "searcher.currency" not in src


def test_llm_client_does_not_import_deal():
    src = pathlib.Path("src/llm/client.py").read_text(encoding="utf-8")
    assert "from src.searcher.adapters.base import Deal" not in src
    assert "import Deal" not in src