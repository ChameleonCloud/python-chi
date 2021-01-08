#!/usr/bin/env python
import inspect
import json
import os
import sys
import types
from unittest import mock

import nbformat.v4 as nbf


def generate_notebook(sections):
    nb = nbf.new_notebook()
    nb['cells'] = [
        nbf.new_markdown_cell(sections['title']),
        nbf.new_markdown_cell(sections['description']),
        nbf.new_markdown_cell(sections['related_modules']),
        #nbf.new_markdown_cell(sections['arguments']),
        nbf.new_markdown_cell('### Code'),
        nbf.new_code_cell(sections['code']),
        nbf.new_markdown_cell('### Example(s)'),
        nbf.new_code_cell(sections['examples']),
    ]
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
    return inspect.getsourcelines(fn)


def get_imports(fn):
    # Mock the 'chi' library
    # module_name = 'chi'
    # chi_module = types.ModuleType(module_name)
    # sys.modules[module_name] = chi_module
    # modules = {}
    # for submodule in ['lease', 'server', 'network']:
    #     submodule_name = f'{module_name}.{submodule}'
    #     submodule_mock = mock.MagicMock(name=submodule_name)
    #     sys.modules[submodule_name] = modules[submodule_name] = submodule_mock
    #     setattr(chi_module, submodule, submodule_mock)
    from contextvars import copy_context
    ctx = copy_context()
    try:
        ctx.run(fn)
    except Exception:
        pass
    print(list(ctx.items()))


if __name__ == '__main__':
    argv = sys.argv[1:]
    file_name, example_name = argv[0].split(':')
    fn = load_function(file_name, example_name)
    if not fn:
        raise RuntimeError(f'Unable to load {example_name} from {file_name}')
    print(get_source(fn))
    print(get_imports(fn))
