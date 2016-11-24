#!/usr/bin/env python
import sys
import setuptools

if not sys.hexversion >= 0x02070000:
    raise RuntimeError("Python 2.7 or newer is required")

from setuptools import setup, find_packages

setup(
    name='bag-o-hammers',
    version='0.1.0',
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
