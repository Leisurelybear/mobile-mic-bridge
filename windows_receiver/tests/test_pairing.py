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
