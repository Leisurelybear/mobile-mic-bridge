from urllib.parse import parse_qs, urlparse

from mobile_mic_receiver.pairing import build_pairing_uri, build_web_pairing_uri


def test_pairing_uri_contains_connection_details() -> None:
    uri = urlparse(
        build_pairing_uri(host='192.168.1.20', port=8765, token='a b')
    )
    assert uri.scheme == 'mobilemic'
    assert uri.netloc == 'connect'
    assert parse_qs(uri.query) == {
        'host': ['192.168.1.20'],
        'port': ['8765'],
        'token': ['a b'],
    }


def test_make_qr_image_is_non_empty() -> None:
    from mobile_mic_receiver.pairing import make_qr_image

    image = make_qr_image(host='192.168.1.20', port=8765, token='secret')
    assert image.size[0] > 0
    assert image.size[1] > 0
    extrema = image.convert('L').getextrema()
    assert extrema[0] < extrema[1]


def test_web_pairing_uri_with_token() -> None:
    uri = urlparse(
        build_web_pairing_uri(host='192.168.1.20', port=8765, token='a b')
    )
    assert uri.scheme == 'http'
    assert uri.hostname == '192.168.1.20'
    assert uri.port == 8765
    assert uri.path in {'', '/'}
    assert parse_qs(uri.query) == {'token': ['a b']}


def test_web_pairing_uri_omits_empty_token() -> None:
    uri = build_web_pairing_uri(host='10.0.0.2', port=9000, token='')
    assert uri == 'http://10.0.0.2:9000/'
    assert 'token' not in uri


def test_app_pairing_uri_still_works() -> None:
    uri = urlparse(
        build_pairing_uri(host='192.168.1.20', port=8765, token='secret')
    )
    assert uri.scheme == 'mobilemic'


def test_make_qr_image_web_mode_non_empty() -> None:
    from mobile_mic_receiver.pairing import make_qr_image

    image = make_qr_image(
        host='192.168.1.20', port=8765, token='secret', mode='web'
    )
    assert image.size[0] > 0
    extrema = image.convert('L').getextrema()
    assert extrema[0] < extrema[1]
