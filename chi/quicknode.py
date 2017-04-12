"""
Fire up a single node on Chameleon to do something with.
"""
import argparse
import functools
import os
import sys


from . import auth
from .lease import Lease


print_nolf = functools.partial(print, end='', flush=True)


def main(argv=None):
    if argv is None:
        argv = sys.argv

    parser = argparse.ArgumentParser(description=__doc__)

    auth.add_arguments(parser)
    parser.add_argument('--node-type', type=str, default='compute')
    parser.add_argument('--key-name', type=str, default='default',
        help='SSH keypair name on OS used to create an instance.')
    parser.add_argument('--image', type=str, default='CC-CentOS7',
        help='Name or ID of image to launch.')
    parser.add_argument('--no-clean', action='store_true',
        help='Do not clean up on failure.')

    args = parser.parse_args()
    session = auth.session_from_args(args)

    print_nolf('Lease: creating...')
    with Lease(session, node_type=args.node_type, _no_clean=args.no_clean) as lease:
        print('started {}'.format(lease))

        print_nolf('Server: creating...')
        server = lease.create_server(key=args.key_name, image=args.image)
        print_nolf('building...')
        server.wait()
        print_nolf('started {}...'.format(server))
        server.associate_floating_ip()
        print('bound ip {} to server.'.format(server.ip))
        input('\n\'ssh cc@{}\' available.\nPress enter to terminate lease and server.'.format(server.ip))
        print_nolf('Tearing down...')
    print('done.')


if __name__ == '__main__':
    sys.exit(main(sys.argv))
