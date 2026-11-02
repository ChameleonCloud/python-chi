"""End-to-end tests of container exec, upload and download on a real site.

They run only when CHI_E2E_CONTAINER names a running container that has
BusyBox or coreutils, with credentials in the environment (OS_*):

    CHI_E2E_CONTAINER=<uuid> pytest tests/e2e

Set CHI_E2E_ZUN_API to use another Zun API version than python-chi's, and
CHI_E2E_SLOW=1 to also run the cases that take minutes or move large
amounts of data.
"""

import hashlib
import os
import tarfile
import threading
import time

import pytest
from zunclient import exceptions
from zunclient.client import Client as ZunClient
from zunclient.common.websocketclient import k8s_exec

from chi import clients
from chi import container as chi_container

CONTAINER = os.environ.get("CHI_E2E_CONTAINER")
SLOW = os.environ.get("CHI_E2E_SLOW") == "1"

pytestmark = pytest.mark.skipif(not CONTAINER, reason="CHI_E2E_CONTAINER isn't set")
slow = pytest.mark.skipif(not SLOW, reason="CHI_E2E_SLOW isn't 1")


@pytest.fixture(scope="module")
def c():
    return chi_container.Container.from_zun_container(
        clients.zun().containers.get(CONTAINER)
    )


@pytest.fixture(scope="module")
def zun():
    # CHI_E2E_ZUN_API tries another API version than python-chi's.
    version = os.environ.get("CHI_E2E_ZUN_API")
    if version:
        return ZunClient(version, session=clients.session())
    return clients.zun()


@pytest.fixture(scope="module")
def zun_tty():
    # Terminals need API 1.42; python-chi asks for 1.41.
    return ZunClient("1.42", session=clients.session())


@pytest.fixture()
def remote_dir(zun):
    path = "/tmp/chi-e2e-%d" % time.monotonic_ns()
    zun.containers.execute_run(CONTAINER, ["mkdir", path], check=True)
    yield path
    zun.containers.execute_run(CONTAINER, ["rm", "-rf", path])


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def running(zun, pattern):
    r = zun.containers.execute_run(CONTAINER, ["pgrep", "-f", pattern])
    return r.returncode == 0


# Container.execute, as notebooks call it today.


def test_execute_returns_output_and_exit_code(c):
    output, code = c.execute("sh -c 'echo out; echo err >&2; exit 3'")
    # stdout and stderr are joined, in no fixed order.
    assert sorted(output.splitlines()) == ["err", "out"]
    assert code == "3"


def test_execute_waits_past_5_seconds(c):
    assert c.execute("sh -c 'sleep 8; echo done'") == ("done\n", "0")


@slow
def test_execute_waits_past_60_seconds_without_output(c):
    assert c.execute("sh -c 'sleep 100; echo done'") == ("done\n", "0")


def test_execute_missing_program_raises(c):
    with pytest.raises(k8s_exec.SessionError, match="executable file not found"):
        c.execute("no-such-program")


def test_execute_large_output(c):
    output, code = c.execute("sh -c 'head -c 10485760 /dev/zero | tr \"\\0\" a'")
    assert (len(output), set(output), code) == (10 << 20, {"a"}, "0")


# upload and download.


def test_upload_then_download_a_file(c, remote_dir, tmp_path):
    src = tmp_path / "blob"
    src.write_bytes(os.urandom(1 << 20))
    c.upload(str(src), remote_dir)
    back = tmp_path / "not" / "yet" / "there"
    c.download(remote_dir + "/blob", str(back))
    assert sha256(back / "blob") == sha256(src)


def test_download_a_directory_lands_in_dest_name(c, zun, remote_dir, tmp_path):
    zun.containers.execute_run(
        CONTAINER,
        [
            "sh",
            "-c",
            "mkdir -p %s/d/sub && echo a > %s/d/a && echo b > %s/d/sub/b"
            % ((remote_dir,) * 3),
        ],
        check=True,
    )
    c.download(remote_dir + "/d", str(tmp_path))
    assert (tmp_path / "d" / "a").read_text() == "a\n"
    assert (tmp_path / "d" / "sub" / "b").read_text() == "b\n"


def test_download_missing_path_raises(c, tmp_path):
    with pytest.raises(exceptions.CommandFailed) as e:
        c.download("/no/such/path", str(tmp_path))
    assert b"No such file" in e.value.stderr


def test_binary_bytes_survive_upload_and_exec(c, zun, remote_dir, tmp_path):
    data = bytes(range(256)) * 64
    (tmp_path / "bin").write_bytes(data)
    c.upload(str(tmp_path / "bin"), remote_dir)
    r = zun.containers.execute_run(CONTAINER, ["cat", remote_dir + "/bin"])
    assert r.stdout == data


@slow
def test_upload_and_download_50_mib(c, remote_dir, tmp_path):
    src = tmp_path / "blob"
    src.write_bytes(os.urandom(50 << 20))
    c.upload(str(src), remote_dir)
    c.download(remote_dir + "/blob", str(tmp_path / "back"))
    assert sha256(tmp_path / "back" / "blob") == sha256(src)


@slow
def test_download_200_mib(c, zun, remote_dir, tmp_path):
    # upload goes through the REST API, which gives up after 60 s, so make
    # the file in the container.
    zun.containers.execute_run(
        CONTAINER,
        ["sh", "-c", "head -c 209715200 /dev/urandom > %s/big" % remote_dir],
        check=True,
    )
    want = zun.containers.execute_run(
        CONTAINER, ["sha256sum", remote_dir + "/big"]
    ).stdout.split()[0]
    c.download(remote_dir + "/big", str(tmp_path))
    assert sha256(tmp_path / "big").encode() == want


# execute_run with input and timeout.


def test_execute_run_input(zun):
    r = zun.containers.execute_run(CONTAINER, ["cat"], input=b"hi\n")
    assert (r.returncode, r.stdout) == (0, b"hi\n")


def test_execute_run_input_from_file(zun, tmp_path):
    (tmp_path / "in").write_bytes(b"x" * 100000)
    with open(tmp_path / "in", "rb") as f:
        r = zun.containers.execute_run(CONTAINER, ["wc", "-c"], input=f)
    assert int(r.stdout) == 100000


def test_execute_run_16_mib_through_cat(zun):
    data = os.urandom(16 << 20)
    r = zun.containers.execute_run(CONTAINER, ["cat"], input=data)
    assert r.stdout == data


@slow
def test_execute_run_input_as_tar_upload(zun, remote_dir, tmp_path):
    # Upload by piping an archive to tar, instead of put_archive.
    src = tmp_path / "blob"
    src.write_bytes(os.urandom(64 << 20))
    with tarfile.open(tmp_path / "a.tar", "w") as tar:
        tar.add(src, arcname="blob")
    with open(tmp_path / "a.tar", "rb") as f:
        zun.containers.execute_run(
            CONTAINER, ["tar", "xf", "-", "-C", remote_dir], input=f, check=True
        )
    r = zun.containers.execute_run(CONTAINER, ["sha256sum", remote_dir + "/blob"])
    assert r.stdout.split()[0] == sha256(src).encode()


def test_execute_run_timeout_keeps_command_running(zun):
    marker = "sleep 31%d" % (time.monotonic_ns() % 1000)
    with pytest.raises(k8s_exec.ExecTimeout) as e:
        zun.containers.execute_run(
            CONTAINER, ["sh", "-c", "echo started; " + marker], timeout=3
        )
    assert e.value.stdout == b"started\n"
    try:
        assert running(zun, marker)
    finally:
        zun.containers.execute_run(CONTAINER, ["pkill", "-f", marker])


# Sessions, as a notebook terminal or a long-running cell would use them.


def test_sink_gets_output_while_the_command_runs(zun):
    arrivals = []
    session = zun.containers.execute_session(
        CONTAINER,
        ["sh", "-c", "for i in 1 2 3; do echo $i; sleep 1; done"],
        stdout=lambda data: arrivals.append((time.monotonic(), data)),
    )
    try:
        assert session.wait(timeout=30) == 0
    finally:
        session.close()
    assert b"".join(d for _, d in arrivals) == b"1\n2\n3\n"
    assert arrivals[-1][0] - arrivals[0][0] > 1.5


def test_sink_to_a_file(zun, tmp_path):
    with open(tmp_path / "out", "wb") as f:
        session = zun.containers.execute_session(
            CONTAINER, ["sh", "-c", "echo to-file"], stdout=f
        )
        try:
            assert session.wait(timeout=30) == 0
        finally:
            session.close()
    assert (tmp_path / "out").read_bytes() == b"to-file\n"


def test_wait_timeout_leaves_session_open(zun):
    session = zun.containers.execute_session(
        CONTAINER, ["sh", "-c", "sleep 4; echo late"]
    )
    try:
        with pytest.raises(k8s_exec.ExecTimeout):
            session.wait(timeout=1)
        assert session.recv(timeout=30) == (k8s_exec.STDOUT, b"late\n")
        assert session.recv(timeout=30) is None
        assert session.exit_code == 0
    finally:
        session.close()


def test_close_keeps_command_running(zun):
    path = "/tmp/chi-e2e-close-%d" % time.monotonic_ns()
    session = zun.containers.execute_session(
        CONTAINER, ["sh", "-c", "sleep 3; touch " + path]
    )
    session.close()
    time.sleep(6)
    r = zun.containers.execute_run(CONTAINER, ["rm", path])
    assert r.returncode == 0


def test_close_stdin_ends_input(zun):
    session = zun.containers.execute_session(
        CONTAINER, ["wc", "-c"], interactive=True, tty=False
    )
    try:
        session.send(b"12345")
        session.close_stdin()
        assert session.recv(timeout=30) == (k8s_exec.STDOUT, b"5\n")
        assert session.wait(timeout=30) == 0
    finally:
        session.close()


def test_one_thread_reads_while_another_waits(zun):
    # A terminal widget reads; a cell waits for the exit code.
    session = zun.containers.execute_session(
        CONTAINER, ["sh", "-c", "for i in 1 2 3; do echo $i; sleep 1; done"]
    )
    out = []

    def read():
        while True:
            message = session.recv(timeout=30)
            if message is None:
                return
            out.append(message[1])

    reader = threading.Thread(target=read)
    reader.start()
    try:
        assert session.wait(timeout=30) == 0
        reader.join(30)
    finally:
        session.close()
    assert b"".join(out) == b"1\n2\n3\n"


def test_tty_resize(zun_tty):
    session = zun_tty.containers.execute_session(
        CONTAINER, ["sh"], interactive=True, tty=True
    )
    try:
        session.resize(123, 45)
        session.send(b"stty size; exit\n")
        out = b""
        while True:
            message = session.recv(timeout=30)
            if message is None:
                break
            out += message[1]
        assert b"45 123" in out
        assert session.exit_code == 0
    finally:
        session.close()
