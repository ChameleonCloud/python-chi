import collections
import errno
import socket
import time

from fabric import api as fapi
from fabric import network as fnet
import paramiko

fapi.env.warn_only = True
fapi.env.use_ssh_config = True
# fapi.env.abort_on_prompts = True


expected_wait_errors = (
    # while the ssh service starting, it can accept connections but auth isn't fully set.
    paramiko.AuthenticationException,
    #
    paramiko.SSHException,
    # local interruptions?
    paramiko.ssh_exception.NoValidConnectionsError,
    # server might be down while starting
    socket.timeout,
    # if the floating IP is still kinda floating and not getting routed.
    OSError, # filter so only capturing errno.ENETUNREACH
)


def _nothing(*args, **kwargs):
    pass


def dotdotdot(*args, **kwargs):
    print('.', end='', flush=True)


def wait(host, username, callback='dots'):
    error_counts = {exc_type: 0 for exc_type in expected_wait_errors}
    sub_errors = 0
    if callback == 'dots':
        callback = dotdotdot
    elif callback is None:
        callback = _nothing
    else:
        if not isinstance(callback, collections.Callable):
            raise ValueError("callback isn't callable.")

    for attempt in range(150):
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.WarningPolicy())
        try:
            client.connect(host, username=username, timeout=10)

        # except expected_wait_errors as e:
        #     if isinstance(e, OSError):
        #         # we only want to capture "network unreachable"
        #         if e.errno != errno.ENETUNREACH:
        #             raise
        #
        #     for exc_type in error_counts:
        #         if type(e) == exc_type:
        #             error_counts[exc_type] += 1
        #             break
        #     else:
        #         sub_errors += 1
        #         print('semi-unexpected error:', type(e), str(e))
        #
        #     if error_counts[paramiko.AuthenticationException] > 5:
        #         raise RuntimeError('auth not working')
        #
        #     if error_counts[socket.timeout] > 100:
        #         raise RuntimeError('timed out too much')
        except paramiko.AuthenticationException as e:
            # while the ssh service starting, it can accept connections but auth isn't fully set.
            pass
        except paramiko.SSHException as e:
            # local interruptions?
            pass
        except paramiko.ssh_exception.NoValidConnectionsError as e:
            # server might be down while starting
            pass
        except socket.timeout as e:
            # if the floating IP is still kinda floating and not getting routed.
            pass
        except OSError as e:
            # filter so only capturing errno.ENETUNREACH
            if e.errno != errno.ENETUNREACH:
                raise
        else:
            print('<wait over>')
            break
        finally:
            client.close()

        callback(attempt)
        time.sleep(10)


class RemoteControl(object):
    def __init__(self, *, ip=None, server=None, user='cc'):
        self.server = server
        self.user = user
        if ip is None:
            if server is None:
                raise RuntimeError('ip or server must be provided.')
            self.ip = server.ip
        else:
            self.ip = ip

    def wait(self):
        """
        Wait for server to be SSH-able (tolerate connection failures for a bit.)
        """
        wait(self.ip, self.user)

    def run(self, *args, **kwargs):
        with fapi.settings(user=self.user, host_string=self.ip):
            return fapi.run(*args, **kwargs)

    def sudo(self, *args, **kwargs):
        with fapi.settings(user=self.user, host_string=self.ip):
            return fapi.sudo(*args, **kwargs)
