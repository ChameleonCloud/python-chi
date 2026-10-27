"""End-to-end tests of what people run in containers from a notebook.

- A long-running command that stops to ask a question, like apt-get.
- A program that runs until it's told to quit, like vim or htop.
- A program that streams data, like a sensor, into a local plot.

CHI_E2E_CONTAINER names a running BusyBox container; the apt-get, vim and
htop cases also need CHI_E2E_DEBIAN_CONTAINER, a running Debian container
that can reach a Debian mirror. Set CHI_E2E_ARTIFACTS to a directory to
keep the plot the streaming test draws.
"""

import os
import threading
import time

import pytest
from zunclient.client import Client as ZunClient

from chi import clients

CONTAINER = os.environ.get("CHI_E2E_CONTAINER")
DEBIAN = os.environ.get("CHI_E2E_DEBIAN_CONTAINER")

pytestmark = pytest.mark.skipif(not CONTAINER, reason="CHI_E2E_CONTAINER isn't set")
debian = pytest.mark.skipif(not DEBIAN, reason="CHI_E2E_DEBIAN_CONTAINER isn't set")


@pytest.fixture(scope="module")
def zun():
    # Terminals and stdin need API 1.42; python-chi asks for 1.41.
    return ZunClient("1.42", session=clients.session())


def terminal(zun, container, args, width=100, height=30):
    session = zun.containers.execute_session(
        container, args, interactive=True, tty=True
    )
    session.resize(width, height)
    return session


def read_until(session, pattern, timeout):
    """Read output until pattern appears in it; return all of it."""
    deadline = time.monotonic() + timeout
    out = b""
    while pattern not in out:
        message = session.recv(timeout=max(deadline - time.monotonic(), 0.01))
        if message is None:
            raise AssertionError(
                "exited before %r; last output %r" % (pattern, out[-500:])
            )
        out += message[1]
    return out


def read_to_end(session, timeout):
    """Read output until the command exits; return all of it."""
    deadline = time.monotonic() + timeout
    out = b""
    while True:
        message = session.recv(timeout=max(deadline - time.monotonic(), 0.01))
        if message is None:
            return out
        out += message[1]


class Lines:
    """A sink that calls on_line with each whole line of output, as bytes.

    Output arrives in chunks that can end partway through a line.
    """

    def __init__(self, on_line):
        self.on_line = on_line
        self.rest = b""

    def __call__(self, data):
        self.rest += data
        *lines, self.rest = self.rest.split(b"\n")
        for line in lines:
            self.on_line(line)


# 1. A long-running command that stops to ask a question.


def test_answer_a_prompt_after_progress_output(zun):
    session = terminal(
        zun,
        CONTAINER,
        [
            "sh",
            "-c",
            "for i in 1 2 3; do echo working $i/3; sleep 1; done;"
            ' printf "Do you want to continue? [Y/n] "; read a; echo answer=$a',
        ],
    )
    try:
        started = time.monotonic()
        out = read_until(session, b"working 1/3", timeout=30)
        first = time.monotonic() - started
        out += read_until(session, b"[Y/n] ", timeout=30)
        # The progress arrived as it was printed, not all at the prompt.
        assert time.monotonic() - started - first > 1.5
        session.send(b"y\r")
        out += read_to_end(session, timeout=30)
        assert b"answer=y" in out
        assert session.exit_code == 0
    finally:
        session.close()


@debian
def test_apt_get_update_and_install_answering_the_prompt(zun):
    session = terminal(
        zun,
        DEBIAN,
        ["sh", "-c", "apt-get update && apt-get install htop vim-tiny"],
        width=120,
    )
    try:
        out = read_until(session, b"[Y/n] ", timeout=900)
        assert b"Reading package lists" in out
        session.send(b"y\r")
        out += read_to_end(session, timeout=900)
        assert session.exit_code == 0, out[-2000:]
    finally:
        session.close()
    r = zun.containers.execute_run(DEBIAN, ["sh", "-c", "command -v htop vim.tiny"])
    assert r.returncode == 0


# 2. A program that runs until it's told to quit.


def test_vi_edits_a_file(zun):
    path = "/tmp/chi-e2e-vi-%d" % time.monotonic_ns()
    session = terminal(zun, CONTAINER, ["vi", path], width=80, height=24)
    try:
        # Keys sent before vi has drawn its screen are lost.
        read_until(session, b"~", timeout=30)
        session.send(b"ihello from vi\x1b")
        # Keys right after Escape read as one escape sequence, as in any
        # terminal, so pause before the command.
        time.sleep(0.5)
        session.send(b":wq\r")
        assert session.wait(timeout=30) == 0
    finally:
        session.close()
    r = zun.containers.execute_run(
        CONTAINER, ["sh", "-c", "cat %s; rm %s" % (path, path)]
    )
    assert r.stdout == b"hello from vi\n"


def test_top_redraws_and_quits(zun):
    session = terminal(zun, CONTAINER, ["top"])
    try:
        read_until(session, b"PID", timeout=30)
        session.resize(140, 40)
        read_until(session, b"PID", timeout=30)
        session.send(b"q")
        assert session.wait(timeout=30) == 0
    finally:
        session.close()


def test_ctrl_c_stops_a_terminal_program(zun):
    # As with docker exec -it and kubectl exec -it, Ctrl-C is a key like any
    # other; the terminal in the container turns it into SIGINT.
    session = terminal(zun, CONTAINER, ["sleep", "300"])
    try:
        time.sleep(1)
        session.send(b"\x03")
        assert session.wait(timeout=30) == 130
    finally:
        session.close()


def test_close_leaves_a_terminal_program_running(zun):
    # As with docker exec -it and kubectl exec -it, closing the terminal
    # doesn't stop what runs in it.
    session = terminal(zun, CONTAINER, ["top"])
    try:
        read_until(session, b"PID", timeout=30)
    finally:
        session.close()
    time.sleep(3)
    try:
        r = zun.containers.execute_run(CONTAINER, ["pgrep", "-x", "top"])
        assert r.returncode == 0
    finally:
        zun.containers.execute_run(CONTAINER, ["pkill", "-x", "top"])


@debian
def test_vim_edits_a_file(zun):
    path = "/tmp/chi-e2e-vim-%d" % time.monotonic_ns()
    session = terminal(zun, DEBIAN, ["vim.tiny", path], width=80, height=24)
    try:
        read_until(session, b"~", timeout=30)
        session.send(b"ihello from vim\x1b")
        time.sleep(0.5)
        session.send(b":wq\r")
        assert session.wait(timeout=30) == 0
    finally:
        session.close()
    r = zun.containers.execute_run(DEBIAN, ["sh", "-c", "cat %s; rm %s" % (path, path)])
    assert r.stdout == b"hello from vim\n"


@debian
def test_htop_redraws_and_quits(zun):
    session = terminal(zun, DEBIAN, ["htop"])
    try:
        read_until(session, b"Load average", timeout=30)
        session.resize(140, 40)
        read_until(session, b"Load average", timeout=30)
        session.send(b"q")
        assert session.wait(timeout=30) == 0
    finally:
        session.close()


# 3. A program that streams data into a local plot.


def test_stream_sensor_readings_into_a_plot(zun, tmp_path):
    # The sensor prints "<n> <reading>" every 0.1 s until it's stopped.
    tag = "chi-e2e-sensor-%d" % time.monotonic_ns()
    sensor = [
        "awk",
        "-v",
        "tag=" + tag,
        "BEGIN { srand(); for (n = 0; ; n++) {"
        ' printf "%d %.3f\\n", n, sin(n / 5) + rand() / 5; fflush();'
        ' system("sleep 0.1") } }',
    ]
    points = []
    enough = threading.Event()

    def plot(line):
        n, reading = line.split()
        points.append((time.monotonic(), int(n), float(reading)))
        if len(points) == 40:
            enough.set()

    session = zun.containers.execute_session(CONTAINER, sensor, stdout=Lines(plot))
    try:
        assert enough.wait(timeout=60)
    finally:
        session.close()
        zun.containers.execute_run(CONTAINER, ["pkill", "-f", tag])
    readings = points[:40]
    assert [n for _, n, _ in readings] == list(range(40))
    # The readings arrived as the sensor made them, over about 4 s.
    assert readings[-1][0] - readings[0][0] > 3

    matplotlib = pytest.importorskip("matplotlib")
    matplotlib.use("Agg")
    from matplotlib import pyplot

    figure, axes = pyplot.subplots()
    t0 = readings[0][0]
    axes.plot([t - t0 for t, _, _ in readings], [r for _, _, r in readings], ".-")
    axes.set_xlabel("seconds since the first reading arrived")
    axes.set_ylabel("reading")
    figure.savefig(
        os.path.join(os.environ.get("CHI_E2E_ARTIFACTS", tmp_path), "sensor.png")
    )
    pyplot.close(figure)
