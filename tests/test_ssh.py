from chi.ssh import Remote

LOCALHOST = "127.0.0.1"


def test_get():
    r = Remote(ip=LOCALHOST)
    assert r.host == LOCALHOST
    assert r.user == "cc"


def test_get_from_server():
    class FakeServer:
        def __init__(self):
            self.ip = LOCALHOST

    r = Remote(server=FakeServer())
    assert r.host == LOCALHOST
    assert r.user == "cc"
