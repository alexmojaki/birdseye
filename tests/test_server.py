from unittest.mock import patch

import pytest
from flask.templating import render_template

from birdseye import server


@pytest.mark.parametrize('flag', ['--dark-mode', '--dark'])
def test_dark_mode_flags(flag):
    with patch.object(server.app, 'run') as run:
        server.main([flag])

    assert server.app.config['DARK_MODE']
    run.assert_called_once_with(
        port=7777,
        host=None,
        use_reloader=False,
    )


def test_dark_mode_defaults_to_disabled():
    with patch.object(server.app, 'run'):
        server.main([])

    assert not server.app.config['DARK_MODE']


@pytest.mark.parametrize('value', ['1', 'true', 'TRUE', 'yes', 'YES', 'on', 'ON', 'online'])
def test_dark_mode_can_be_enabled_with_environment_variable(monkeypatch, value):
    monkeypatch.setenv('BIRDSEYE_DARK', value)

    with patch.object(server.app, 'run'):
        server.main([])

    assert server.app.config['DARK_MODE']


@pytest.mark.parametrize('value', ['', '0', 'false', 'no', 'off', 'disabled'])
def test_dark_mode_environment_variable_ignores_falsey_values(monkeypatch, value):
    monkeypatch.setenv('BIRDSEYE_DARK', value)

    with patch.object(server.app, 'run'):
        server.main([])

    assert not server.app.config['DARK_MODE']


def test_dark_theme_is_rendered_only_when_enabled():
    with server.app.test_request_context():
        server.app.config['DARK_MODE'] = True
        rendered = render_template('base.html')
        assert '#171a1f' in rendered
        assert '#example-code.hljs' in rendered
        assert '#code, #code.hljs' in rendered

        server.app.config['DARK_MODE'] = False
        assert '#171a1f' not in render_template('base.html')
