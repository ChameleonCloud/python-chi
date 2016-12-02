# coding: utf-8
from __future__ import absolute_import, print_function, unicode_literals

import codecs
import json

import requests


def reporter_factory(settings_file):
    with codecs.open(settings_file, 'r', encoding='utf-8') as f:
        settings = json.load(f)

    if 'webhook' not in settings:
        raise ValueError('settings file must contain "webhook" key at minimum')

    def _reporter(message):
        payload = {
            'username': 'Box o\' Hammers',
            'icon_emoji': ':hammer:',
            'text': message,
            'channel': '#notifications',
        }
        return requests.post(settings['webhook'], json=payload)

    return _reporter
