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


def test_source_links_are_available_before_and_after_joining():
    join_template = Path("app/templates/_player_form.html").read_text()
    index_template = Path("app/templates/index.html").read_text()

    assert "Presented live at Big Sky Dev Con 2026" in join_template
    assert "View source on GitHub" in join_template
    assert 'aria-label="View source code on GitHub"' in index_template
    assert join_template.count("https://github.com/scriptogre/hyperspace") == 1
    assert index_template.count("https://github.com/scriptogre/hyperspace") == 1
