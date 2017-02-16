from __future__ import print_function

import os
import errno
import shutil
from six.moves import input, urllib

from invoke import task

ROOT = os.path.abspath(os.path.dirname(__file__))
PACKAGE_NAME = 'hammers'


def get_version():
    with open('hammers/__init__.py') as f:
        for line in f:
            if line.startswith('__version__'):
                _, version = line.split('=')
                version = version.strip().strip('\'\"')
                return version
        else:
            raise RuntimeError('couldn\'t find version')


@task
def clean(ctx):
    rm_targets = ['build', 'dist', '{}.egg-info'.format(PACKAGE_NAME)]

    for t in rm_targets:
        try:
            print('removing {}...'.format(t), end=' ')
            shutil.rmtree(os.path.join(ROOT, t))
            print('OK.')
        except OSError as e:
            if e.errno != errno.ENOENT:
                raise
            print('already gone.')


@task
def build(ctx):
    ctx.run('python setup.py sdist bdist_wheel')


@task
def install(ctx):
    if int(os.environ.get('INSTALL_WHEEL', 0)):
        print('installing bdist_wheel...')
        ctx.run('pip install dist/{}-*.whl'.format(PACKAGE_NAME))
    else:
        print('installing sdist...')
        ctx.run('pip install dist/{}-*.tar.gz'.format(PACKAGE_NAME))


@task
def publish(ctx):
    version = get_version()
    tag_info = input('Enter tag description for "v{}":\n'.format(version))

    ctx.run('twine upload dist/*')
    ctx.run('git tag -a v{} -m "{}"'.format(version, tag_info))
