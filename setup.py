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
    url='https://github.org/ChameleonCloud/bag-o-hammers',

    long_description=open('README.rst', 'r').read(),
    keywords=[
        'chameleon-cloud', 'chameleon', 'openstack',
    ],

    entry_points={
        'console_scripts': [
            'neutron-reaper = hammers.scripts.reaper:main',
        ],
    },

    classifiers=[
        'Development Status :: 4 - Beta',
        'Environment :: OpenStack',
        'Intended Audience :: System Administrators',
        'Topic :: Utilities',
    ],

    install_requires=[
        # 'mysqlclient>=1.3.6', # assume this is installed; could also be mysql-python
    ],
)
