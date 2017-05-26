import argparse
import functools
import io
import os
import shlex
import subprocess
import sys

from fabric import api as fapi
from fabric import context_managers as fcm

from ccmanage import auth
from ccmanage.lease import Lease
from ccmanage.ssh import RemoteControl
from ccmanage.util import random_base32


print_nolf = functools.partial(print, end='', flush=True)


def run(command, **kwargs):
    runargs = {
        'stdout': subprocess.PIPE,
        'stderr': subprocess.PIPE,
        'universal_newlines': True,
        'shell': False
    }
    runargs.update(kwargs)
    if not runargs['shell']:
        command = shlex.split(command)
    return subprocess.run(command, **runargs)


def get_local_rev(path):
    # proc = run('git status', cwd='CC-Ubuntu16.04')
    # print(proc.stdout)
    head = run('git rev-parse HEAD', cwd=str(path)).stdout.strip()
    return head


def do_build(ip, variant='base'):
    remote = RemoteControl(ip=ip)
    print('waiting for remote to start')
    remote.wait()
    print('remote contactable!')

    # init remote repo
    remote.run('rm -rf ~/build.git', quiet=True)
    out = remote.run('git init --bare build.git', quiet=True)
    print(out)

    # push to remote
    proc = run(f'git push --all ssh://cc@{ip}/~/build.git', cwd='CC-Ubuntu16.04', env={
        'GIT_SSH_COMMAND': 'ssh -o UserKnownHostsFile=/dev/null -o StrictHostKeyChecking=no',
    })
    print(proc.stdout)
    print(proc.stderr)
    if proc.returncode != 0:
        raise RuntimeError()

    # checkout local rev on remote
    head = get_local_rev('CC-Ubuntu16.04')
    remote.run('rm -rf ~/build', quiet=True)
    remote.run('git clone ~/build.git ~/build', quiet=True)
    with fapi.cd('/home/cc/build'):
        remote.run(f'git -c advice.detachedHead=false checkout {head}')
        remote.run('ls -a')

    # install build reqs
    remote.run('sudo bash ~/build/install-reqs.sh', pty=True, quiet=True)

    # do build
    out = io.StringIO()
    with fapi.cd('/home/cc/build/'):
    #     out = fapi.run('bash create-image.sh', pty=False, quiet=True)
        remote.run(f'bash create-image.sh {variant}', pty=True, capture_buffer_size=10000, stdout=out)

    with open('build.log', 'w') as f:
        print(f.write(out.getvalue()))

    out.seek(0)
    ibi = f'[{ip}] out: Image built in '
    for line in out:
        if not line.startswith(ibi):
            continue
        output_file = line[len(ibi):].strip()
        break
    else:
        raise RuntimeError("didn't find output file in logs.")
    print(output_file)
    checksum = remote.run(f'md5sum {output_file}').split()[0].strip()

    return {
        'image_loc': output_file,
        'image_rev': head,
        'checksum': checksum,
    }


def do_upload(ip, rc, image_rev, image_loc):
    remote = RemoteControl(ip=ip)

    with fcm.shell_env(**rc):#, fapi.cd('/home/cc/build'):
        out = remote.run(('glance image-create '
                       '--name "CC-Ubuntu16.04-{}" '
                       '--disk-format qcow2 '
                       '--container-format bare '
                       '--file {}').format(image_rev, image_loc))

    image_data = {}
    for line in out.splitlines():
        parts = [p.strip() for p in line.strip(' |\n\t').split('|')]
        if len(parts) != 2:
            continue
        key, value = parts
        if key == 'Property':
            continue
        image_data[key] = value

    return image_data


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
    session, rc = auth.session_from_args(args, rc=True)

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

        build_results = do_build(server.ip)
        glance_results = do_upload(
            server.ip,
            rc,
            image_rev=build_results['image_rev'],
            image_loc=build_results['image_loc'],
        )

        if build_results['checksum'] != glance_results['checksum']:
            raise RuntimeError('checksum mismatch! build: {} vs glance: {}'.format(
                repr(build_results['checksum']),
                repr(glance_results['checksum']),
            ))

        server.rebuild(glance_results['id'])
        server.wait()

        input('pausing.')

        print_nolf('Tearing down...')
    print('done.')


if __name__ == '__main__':
    sys.exit(main(sys.argv))
