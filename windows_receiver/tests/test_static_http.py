from mobile_mic_receiver.static_http import handle_http, load_asset, resolve_static


def test_resolve_root_and_index() -> None:
    assert resolve_static('/') == ('index.html', 'text/html; charset=utf-8')
    assert resolve_static('/index.html') == (
        'index.html',
        'text/html; charset=utf-8',
    )


def test_resolve_strips_query() -> None:
    assert resolve_static('/app.js?token=x') == (
        'app.js',
        'application/javascript; charset=utf-8',
    )


def test_resolve_dsp_js() -> None:
    assert resolve_static('/dsp.js') == (
        'dsp.js',
        'application/javascript; charset=utf-8',
    )


def test_handle_get_dsp_ok() -> None:
    response = handle_http('/dsp.js', 'GET')
    assert response is not None
    assert response.status_code == 200
    assert b'MobileMicDsp' in bytes(response.body)


def test_resolve_unknown_is_none() -> None:
    assert resolve_static('/secret') is None
    assert resolve_static('/../pairing.py') is None
    assert resolve_static('/mic') is None


def test_handle_get_index_ok() -> None:
    response = handle_http('/', 'GET')
    assert response is not None
    assert response.status_code == 200
    assert b'Mobile Mic Bridge' in bytes(response.body)
    assert 'text/html' in response.headers['Content-Type']


def test_handle_head_has_empty_body() -> None:
    response = handle_http('/styles.css', 'HEAD')
    assert response is not None
    assert response.status_code == 200
    assert bytes(response.body) == b''


def test_handle_post_method_not_allowed() -> None:
    response = handle_http('/app.js', 'POST')
    assert response is not None
    assert response.status_code == 405


def test_handle_unknown_returns_none() -> None:
    assert handle_http('/nope', 'GET') is None


def test_asset_root_frozen(monkeypatch, tmp_path) -> None:
    import sys

    assets = tmp_path / 'mobile_mic_receiver' / 'web_assets'
    assets.mkdir(parents=True)
    (assets / 'index.html').write_text('ok', encoding='utf-8')
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.setattr(sys, '_MEIPASS', str(tmp_path), raising=False)
    assert load_asset('index.html') == b'ok'
