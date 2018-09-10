import chi
import pytest

def setup_function():
    chi.reset()

def test_fetch():
    value = 'KEYNAME'
    chi.set('key_name', value)
    assert chi.get('key_name') == value

def test_fetch_invalid_key():
    with pytest.raises(KeyError):
        chi.get('some_invalid_key')

def test_session():
    session = chi.session()
    assert session
