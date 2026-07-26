from urllib.parse import parse_qs, urlparse

from mobile_mic_receiver.pairing import build_pairing_uri


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
