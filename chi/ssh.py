from __future__ import absolute_import, print_function, unicode_literals

import collections
import errno
import os
import socket
import time

from fabric import api as fapi
from fabric import network as fnet
import paramiko

fapi.env.abort_on_prompts = True
fapi.env.disable_known_hosts = True # FIXME meh
fapi.env.use_ssh_config = True
fapi.env.warn_only = True

fapi.env.key_filename = os.environ.get('SSH_KEY_FILE', None)

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
    # error_counts = {exc_type: 0 for exc_type in expected_wait_errors}
    # sub_errors = 0
    error_counts = collections.Counter()
    if callback == 'dots':
        callback = dotdotdot
    elif callback is None:
        callback = _nothing
    else:
        if not isinstance(callback, collections.Callable):
            raise ValueError("callback isn't callable.")

    key_filename = fapi.env.key_filename

    for attempt in range(150):
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.WarningPolicy())
        try:
            client.connect(
                host,
                username=username,
                timeout=10,
                key_filename=key_filename,
            )

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
            error_counts['paramiko.AuthenticationException'] += 1
            pass
        except paramiko.SSHException as e:
            # local interruptions?
            error_counts['paramiko.SSHException'] += 1
            pass
        except paramiko.ssh_exception.NoValidConnectionsError as e:
            # server might be down while starting
            error_counts['paramiko.ssh_exception.NoValidConnectionsError'] += 1
            pass
        except socket.timeout as e:
            # if the floating IP is still kinda floating and not getting routed.
            error_counts['socket.timeout'] += 1
            pass
        except OSError as e:
            # filter so only capturing errno.ENETUNREACH
            if e.errno != errno.ENETUNREACH:
                raise
            error_counts['ENETUNREACH'] += 1
        else:
            print('<wait over>')
            break
        finally:
            client.close()

        callback(attempt)
        time.sleep(10)
    else:
        raise RuntimeError('failed to connect to {}@{}: {}'.format(username, host, error_counts))


class RemoteControl(object):
    def __init__(self, ip=None, server=None, user='cc'):
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
