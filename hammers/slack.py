# coding: utf-8
from __future__ import absolute_import, print_function, unicode_literals

import codecs
import json
import socket

import requests

from hammers import __version__ as VERSION


class Slackbot(object):
    def __init__(self, settings_file):
        with codecs.open(settings_file, 'r', encoding='utf-8') as f:
            self.settings = json.load(f)

        if 'webhook' not in self.settings:
            raise ValueError('settings file must contain "webhook" key at minimum')

        host = socket.getfqdn()
        try:
            host = self.settings['hostname_names'][host]
        except KeyError:
            host = '({})'.format(host)
        self.host = host

    def post(self, script, payload, color='#ccc'):
        payload = {
            'username': 'Box o\' Hammers',
            'icon_emoji': ':hammer:',
            # 'channel': '#notifications', # use default for webhook
            'attachments': [{
                'fallback': '{} | {} | {}'.format(self.host, script, payload),
                'mrkdwn_in': ['text'],
                'color': color,
                'author_name': 'chameleoncloud/hammers@{}'.format(VERSION),
                'author_link': 'https://github.com/ChameleonCloud/hammers/',
                'title': '{} on {}'.format(script, self.host),
                'text': payload,
            }]
        }

        response = requests.post(self.settings['webhook'], json=payload)
        if response.status_code != requests.codes.OK:
            print('Non-OK ({}) response from Slack: {}'.format(
                response.status_code, response.content[:400]), file=sys.stderr)
        return response
