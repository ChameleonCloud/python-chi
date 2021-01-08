#!/usr/bin/env python
import inspect
import json
import os
import sys

import nbformat.v4 as nbf


def generate_notebook(*example_fns):
    nb = nbf.new_notebook()

    for fn in example_fns:
        docs = get_docs(fn)
        source = get_source(fn).replace(docs, '')
        nb['cells'].extend([
            nbf.new_markdown_cell(f'## {docs}'),
            nbf.new_code_cell(source),
        ])

    return nb


def write_notebook(nb, file_name):
    print(f'write notebook: {file_name}')
    os.makedirs(os.path.dirname(file_name), exist_ok=True)
    with open(file_name, 'w') as f:
        f.write(json.dumps(nb, indent=2))


def load_function(file_name, example_name):
    import importlib
    module_name = file_name.replace('/', '.').replace('.py', '')
    module = importlib.import_module(module_name)
    return getattr(module, example_name, None)


def get_source(fn):
    source = inspect.getsource(fn)
    if fn.__doc__:
        # This is some pretty kludgy code, but basically it's trying to null
        # out the docstring documentation for the function.
        source = (source.replace(fn.__doc__, '')
            .replace('"""', '')
            .replace(':\n    \n', ':\n'))
    return source


def get_docs(fn):
    return inspect.getdoc(fn)


# TODO: use an actual CLI arg parser.
if __name__ == '__main__':
    argv = sys.argv[1:]
    fns = []
    for filearg in argv:
        file_name, example_name = filearg.split(':')
        fn = load_function(file_name, example_name)
        if not fn:
            raise RuntimeError(f'Unable to load {example_name} from {file_name}')
        fns.append(fn)
    with open('notebook.ipynb', 'w') as f:
        f.write(json.dumps(generate_notebook(*fns), indent=2) + '\n')
