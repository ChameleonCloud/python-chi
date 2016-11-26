# coding: utf-8
from __future__ import absolute_import, print_function, unicode_literals

import os
import codecs
import glob
import logging
import stat
CP_MODERN = True
try:
    import configparser
except ImportError:
    try:
        from backports import configparser
    except ImportError:
        import io
        import ConfigParser as configparser
        CP_MODERN = False

__all__ = ['MyCnf', 'MYCNF_PATHS']

KEYERROR_LIKE_OPTIONERRORS = (
    configparser.NoSectionError,
    configparser.NoOptionError,
)

# https://dev.mysql.com/doc/refman/5.7/en/option-files.html
# https://mariadb.com/kb/en/mariadb/configuring-mariadb-with-mycnf/
MYCNF_PATHS = [
    '/etc/my.cnf',
    '/etc/mysql/my.cnf',
#     'SYSCONFDIR/my.cnf',
#     'defaults-extra-file' # The file specified with --defaults-extra-file, if any
    '~/.my.cnf',
    '~/.mylogin.cnf',
]


class MyCnf(object):
    L = logging.getLogger('.'.join([__name__, 'MyCnf']))

    def __init__(self, paths=None):
        if paths is None:
            paths = MYCNF_PATHS

        self.path_stack = list(reversed(paths))
        self.cp = configparser.ConfigParser(allow_no_value=True)

        self.load()

    def valid_path(self, path):
        self.L.debug('checking path {} for validity'.format(path))
        try:
            cnf_stat = os.stat(path)
        except (IOError, OSError):
            self.L.debug('failed to stat path {} (can\'t read/doesn\'t exist?)'.format(path))
            return False

        if cnf_stat.st_mode & stat.S_IWOTH:
            self.L.debug('path {} is world-writable, ignoring'.format(path))
            return False

        return True

    def read(self, path):
        with codecs.open(path) as f:
            for line in f:
                if line.startswith('!'):
                    self.L.debug('found magic directive, line: "{}"'.format(line))

                    self.magic(path, line)
                else:
                    yield line

    def magic(self, sourcefile, line):
        directive, args = line.split(None, 1)
        directive = directive.lstrip('!')
        return {
            'include': self.include,
            'includedir': self.includedir,
        }[directive](sourcefile, args)

    def include(self, source_file, include):
        new_path = os.path.join(os.path.dirname(source_file), include)
        self.L.debug('adding path from source file "{}": {}'.format(
                source_file, new_path))
        self.path_stack.append(new_path)

    def includedir(self, source_file, includedir):
        new_paths = list(glob.iglob(os.path.join(os.path.dirname(source_file), includedir, '*.cnf')))
        self.L.debug('adding paths from source file "{}" found in dir "{}": {}'.format(
                source_file, includedir, new_paths))
        self.path_stack.extend(new_paths)

    def load(self):
        while self.path_stack:
            path = self.path_stack.pop()
            self.L.debug('processing possible path "{}"'.format(path))

            path = os.path.expanduser(path)

            if not self.valid_path(path):
                continue

            self.L.debug('loading/merging file "{}"'.format(path))
            self.read_file(path)

    def read_file(self, path):
        if CP_MODERN:
            self.cp.read_file(self.read(path))
        else:
            buf = io.StringIO('\n'.join(self.read(path)))
            self.cp.readfp(buf)

    def __iter__(self):
        if CP_MODERN:
            return iter(self.cp)
        else:
            return iter(['DEFAULT'] + self.cp.sections())

    def __getitem__(self, key):
        try:
            if CP_MODERN:
                d = dict(self.cp[key])
            else:
                d = dict(self.cp.items(key))
        except KEYERROR_LIKE_OPTIONERRORS as e:
            raise KeyError(str(e))

        return d


if __name__ == '__main__':
    import json
    logging.basicConfig(level=logging.DEBUG)
    mycnf = MyCnf(MYCNF_PATHS)
    print(json.dumps({sec: mycnf[sec] for sec in mycnf}, indent=4))
