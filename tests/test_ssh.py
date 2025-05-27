from chi.ssh import Remote

LOCALHOST = "127.0.0.1"


def _context_get_keypair_private_key(key):
    return "fake_key"


def test_get(mocker):
    mocker.patch("chi.context.get", side_effect=_context_get_keypair_private_key)
    r = Remote(ip=LOCALHOST)
    assert r.host == LOCALHOST
    assert r.user == "cc"


def test_get_from_server(mocker):
    class FakeServer:
        def __init__(self):
            self.ip = LOCALHOST

    mocker.patch("chi.context.get", side_effect=_context_get_keypair_private_key)
    r = Remote(server=FakeServer())
    assert r.host == LOCALHOST
    assert r.user == "cc"
