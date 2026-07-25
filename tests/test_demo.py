from pathlib import Path


def test_demo_uses_production_stack_with_lan_override():
    recipe = Path("Justfile").read_text()
    override = Path("docker-compose.demo.yml").read_text()

    assert "ipconfig getifaddr" in recipe
    assert 'DOMAIN="http://${lan_ip}:8000"' in recipe
    assert "-f docker-compose.production.yml" in recipe
    assert "-f docker-compose.demo.yml" in recipe
    assert '"8000:8000"' in override
    assert "DOMAIN: ${DOMAIN:?Run this stack with `just demo`}" in override
