# coding: utf-8
from __future__ import print_function, absolute_import, unicode_literals

import datetime
import getpass
import logging
import re

import requests


def load_osrc(fn, get_pass=False):
    '''Load the RC file dumped out by the dashboard as a dict'''
    envval = re.compile(r'''
        \s* # maybe whitespace
        (?P<key>[A-Za-z0-9_\-$]+)  # variable name
        =
        ([\'\"]?)                  # optional quote
        (?P<value>.*)              # variable content
        \2                         # matching quote
        ''', flags=re.VERBOSE)
    rc = {}
    with open(fn, 'r') as f:
        for line in f:
            match = envval.search(line)
            if not match:
                continue
            match = match.groupdict()
            rc[match['key']] = match['value']

    try:
        password = rc['OS_PASSWORD']
    except KeyError:
        pass
    else:
        if password == '$OS_PASSWORD_INPUT':
            rc.pop('OS_PASSWORD')

    if get_pass:
        rc['OS_PASSWORD'] = getpass.getpass('Enter your password: ')

    return rc


class Auth(object):
    L = logging.getLogger(__name__ + '.Auth')

    required_os_vars = [
        'OS_USERNAME',
        'OS_PASSWORD',
        'OS_TENANT_NAME',
        'OS_AUTH_URL',
    ]

    def __init__(self, rc):
        self.rc = rc
        self.authenticate()

    def authenticate(self):
        response = requests.post(self.rc['OS_AUTH_URL'] + '/tokens', json={
        'auth': {
            'passwordCredentials': {
                'username': self.rc['OS_USERNAME'],
                'password': self.rc['OS_PASSWORD'],
            },
            'tenantName': self.rc['OS_TENANT_NAME']
        }})
        if response.status_code != 200:
            raise RuntimeError(
                'HTTP {}: {}'
                .format(response.status_code, response.content[:400])
            )

        jresponse = response.json()
        try:
            self.access = jresponse['access']
        except KeyError:
            raise RuntimeError(
                'expected "access" key not present in response '
                '(found keys: {})'.format(list(jresponse))
            )

        self._token = self.access['token']['id']
        self.expiry = datetime.datetime.strptime(self.access['token']['expires'], '%Y-%m-%dT%H:%M:%SZ')

        self.L.debug('New token "{}" expires in {:.2f} minutes'.format(
            self._token,
            (self.expiry - datetime.datetime.utcnow()).total_seconds() / 60
        ))

    @property
    def token(self):
        if (self.expiry - datetime.datetime.utcnow()).total_seconds() < 60:
            self.authenticate()

        return self._token

    def endpoint(self, type):
        services = [
            service
            for service
            in self.access['serviceCatalog']
            if service['type'] == type
        ]
        if len(services) < 1:
            raise RuntimeError("didn't find any services matching type '{}'".format(type))
        elif len(services) > 1:
            raise RuntimeError("found multiple services matching type '{}'".format(type))

        service = services[0]

        return service['endpoints'][0]['publicURL']
