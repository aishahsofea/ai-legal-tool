import pytest

from scraper.crypto import DecryptionError, decrypt_envelope, extract_response_key
from tests.conftest import FAKE_RESPONSE_KEY, encrypt_envelope


def test_decrypt_envelope_round_trip():
    envelope = encrypt_envelope({"recordsTotal": 2, "records": [{"a": 1}]})

    result = decrypt_envelope(envelope, FAKE_RESPONSE_KEY)

    assert result == {"recordsTotal": 2, "records": [{"a": 1}]}


def test_decrypt_envelope_wrong_key_raises():
    envelope = encrypt_envelope({"records": []})
    wrong_key = "11" * 32

    with pytest.raises(DecryptionError):
        decrypt_envelope(envelope, wrong_key)


def test_decrypt_envelope_tampered_ciphertext_raises():
    envelope = encrypt_envelope({"records": []})
    import base64
    raw = bytearray(base64.b64decode(envelope["data"]))
    raw[-1] ^= 0xFF
    envelope["data"] = base64.b64encode(bytes(raw)).decode("ascii")

    with pytest.raises(DecryptionError):
        decrypt_envelope(envelope, FAKE_RESPONSE_KEY)


def test_decrypt_envelope_rejects_non_encrypted_shape():
    with pytest.raises(DecryptionError):
        decrypt_envelope({"data": []}, FAKE_RESPONSE_KEY)


def test_decrypt_envelope_rejects_empty_data():
    with pytest.raises(DecryptionError):
        decrypt_envelope({"encrypted": True, "data": ""}, FAKE_RESPONSE_KEY)


def test_extract_response_key_finds_key_in_principal_page():
    html = "<script>\n\t\tconst SEARCH_RESPONSE_KEY = '%s';\t\t\n</script>" % ("ab" * 32)

    assert extract_response_key(html) == "ab" * 32


def test_extract_response_key_raises_when_missing():
    with pytest.raises(DecryptionError):
        extract_response_key("<html>no key here</html>")
