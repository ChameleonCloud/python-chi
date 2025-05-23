import base64
import os
import time
from datetime import datetime, timedelta
from hashlib import md5

import ipywidgets as widgets
from dateutil import tz
from IPython.display import display

from chi.exception import ResourceError


def random_base32(n_bytes):
    rand_bytes = os.urandom(n_bytes)
    return base64.b32encode(rand_bytes).decode("ascii").strip("=")


def sshkey_fingerprint(public_key):
    # See: https://stackoverflow.com/a/6682934
    key = base64.b64decode(public_key.strip().split()[1].encode("ascii"))
    fp_plain = md5(key).hexdigest()
    return ":".join(a + b for a, b in zip(fp_plain[::2], fp_plain[1::2]))


def get_public_network(neutronclient):
    nets = neutronclient.list_networks()["networks"]
    for net in nets:
        if not net["router:external"]:
            continue
        pubnet_id = net["id"]
        break
    else:
        raise RuntimeError("couldn't find public net")
    return pubnet_id


def utcnow():
    return datetime.now(tz=tz.tzutc())


def date_string_in_future(days=1):
    return (utcnow() + timedelta(days=days)).isoformat()


def should_delete(delete_at):
    try:
        return datetime.fromisoformat(delete_at) < utcnow()
    except ValueError:
        return False


class TimerProgressBar:
    def __init__(self):
        self.progress = widgets.IntProgress(
            value=0,
            min=0,
            max=100,
            bar_style="success",
            orientation="horizontal",
        )
        self.label = widgets.Label()

    def display(self):
        display(widgets.HBox([self.label, self.progress]))

    def wait(self, callback, expected_timeout, timeout, interval=5):
        """Wait and update the progress bar.

        Args:
            callback (function): bool function for whether to break
            expected_timeout (int): how long the progress bar should expect to wait for in seconds. Will display 90% when reached
            timeout (int): The time to reach 100% of the progress bar
            interval (int): The time to wait between checking the callback)
        Returns:
            Whether callback returned true before timeout
        """
        expected_proportion = 0.9
        start_time = time.time()
        while time.time() - start_time < timeout:
            if callback():
                self.progress.value = 100
                return True
            elapased = timedelta(seconds=(time.time() - start_time))
            self.label.value = f"{str(elapased).split('.')[0]} elapsed."

            if elapased.total_seconds() < expected_timeout:
                self.progress.value = (
                    100
                    * expected_proportion
                    * elapased.total_seconds()
                    / expected_timeout
                )
            else:
                self.progress.value = 100 * (
                    expected_proportion
                    + (1 - expected_proportion)
                    * (elapased.total_seconds() - expected_timeout)
                    / (timeout - expected_timeout)
                )
            time.sleep(interval)
        return False


def retry_create(max_attempts, create_func, cleanup_func):
    attempt = 0
    while attempt < 3:
        try:
            create_func()
            break
        except Exception as e:
            attempt += 1
            if attempt == max_attempts:
                raise ResourceError(e)
            print(f"Error creating resource on attempt {attempt}/{max_attempts}.")
            cleanup_func()
