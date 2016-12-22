#!/usr/bin/env python
import sys
import setuptools
from setuptools import setup, find_packages

import hammers

setup(
    name='hammers',
    version=hammers.__version__,
    description='Bag of hammers to fix problems',
    packages=find_packages(),

    author='Nick Timkovich',
    author_email='npt@uchicago.edu',
    url='https://github.com/ChameleonCloud/hammers',

    long_description=open('README.rst', 'r').read(),
    keywords=[
        'chameleon-cloud', 'chameleon', 'openstack',
    ],

    entry_points={
        'console_scripts': [
            'conflict-macs = hammers.scripts.conflict_macs:main',
            'curiouser = hammers.scripts.curiouser:main',
            'maintenance-reservation = hammers.scripts.maintenance_reservation:main',
            'neutron-reaper = hammers.scripts.neutron_reaper:main',
            'undead-instances = hammers.scripts.undead_instances:main',
        ],
    },

    classifiers=[
        'Development Status :: 4 - Beta',
        'Environment :: OpenStack',
        'Intended Audience :: System Administrators',
        'Topic :: Utilities',
    ],

    install_requires=[
        'requests',
        # 'mysqlclient>=1.3.6', # assume this is installed; could also be mysql-python
    ],
)
