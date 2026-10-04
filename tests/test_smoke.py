from avsd.config import load_config


def test_config_loads():
    cfg = load_config()
    assert cfg["seed"] == 20261003
    assert cfg["llm"]["backend"] == "none"
    assert cfg["paths"]["raw"].name == "ai-village"
