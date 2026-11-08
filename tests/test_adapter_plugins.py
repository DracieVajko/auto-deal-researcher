import importlib.metadata as md

from src.searcher.adapters import ADAPTER_REGISTRY, load_entry_point_adapters


def test_load_entry_point_adapters_registers_external(monkeypatch):
    class FakeEP:
        name = "acme"

        def load(self):
            class Acme:
                pass

            return Acme

    monkeypatch.setattr(md, "entry_points", lambda group=None: [FakeEP()] if group == "ads.adapters" else [])
    load_entry_point_adapters()
    assert "acme" in ADAPTER_REGISTRY
