# coding: utf-8
from __future__ import absolute_import, print_function, unicode_literals


def drop_prefix(s, start):
    l = len(start)
    if s[:l] != start:
        raise ValueError('string does not start with expected value')
    return s[l:]


if __name__ == '__main__':
    assert drop_prefix('x:1234', 'x:') == '1234'
    assert drop_prefix('abcde', 'abc') == 'de'
    try:
        drop_prefix('1234', 'a')
    except ValueError:
        pass
    else:
        assert False
