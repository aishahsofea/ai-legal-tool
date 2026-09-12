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


def test_decrypt_envelope_passes_through_a_plain_datatables_payload():
    """AGC rolled encryption out one endpoint at a time and can roll it back
    the same way. A plain payload is a valid response, not a decryption
    failure — raising would abort the whole run and lose the endpoints that
    did decrypt."""
    payload = {"draw": 1, "recordsTotal": 2, "data": [{"lgt_act_no": "1"}]}

    assert decrypt_envelope(payload, FAKE_RESPONSE_KEY) == payload


def test_decrypt_envelope_still_rejects_a_shape_that_is_neither():
    """No recordsTotal means it isn't a DataTables payload either — an error
    page or a truncated body must never read as zero records."""
    with pytest.raises(DecryptionError):
        decrypt_envelope({"data": []}, FAKE_RESPONSE_KEY)
