#!/usr/bin/env python
import inspect
import json
import os
from textwrap import dedent

import click
import nbformat.v4 as nbf


INTRO_CELLS = [
    nbf.new_markdown_cell(dedent("""
    First, select which project and site you wish to authenticate against.
    """).strip()),
    nbf.new_code_cell(dedent("""
    import chi

    chi.use_site('CHI@UC')
    # Set to your project's charge code
    chi.set('project_name', 'CH-XXXXXX')
    """).strip())
]


def generate_notebook(*example_fns, title=None):
    nb = nbf.new_notebook()
    nb.cells = []
    nb.metadata.language_info = {
        'name': 'Python',
        'version': 3,
    }
    nb.metadata['nbsphinx'] = {'execute': 'never'}

    if title:
        nb.cells.append(nbf.new_markdown_cell(f'# {title}'))

    # Put in the generic intro cells
    nb.cells.extend(INTRO_CELLS)

    for fn in example_fns:
        docs = get_docs(fn)
        source = get_source(fn).replace(docs, '')
        nb.cells.extend([
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
    lines = [l for l in source.split('\n') if (not l or l.startswith(' '))]
    return dedent('\n'.join(lines))


def get_docs(fn):
    docstring = inspect.getdoc(fn)
    # Parse "Uses" section
    # print(docstring)
    # print(USES_REGEX.match(docstring))
    return docstring


def generate(examples, output_file=None, title=None):
    fns = []
    for example_ref in examples:
        file_name, fn_name = example_ref.split(':')
        fn = load_function(file_name, fn_name)
        if not fn:
            raise RuntimeError(f'Unable to load {fn_name} from {file_name}')
        fns.append(fn)
    with open(output_file, 'w') as f:
        contents = json.dumps(generate_notebook(*fns, title=title), indent=2)
        f.write(contents + '\n')


@click.command()
@click.option('--output-file', default='notebook.ipynb',
              help='The output notebook file')
@click.option('--title', help='A title to give the Notebook')
@click.argument('examples', nargs=-1)
def cli(examples, output_file=None, title=None):
    """Generate a notebook from a list of example functions.

    EXAMPLES are expected to be a list of files and the functions located
    within those files, for example, to inline the 'reserve_node' function
    located in 'tests/test_lease.py':

      generate_notebook.py tests/test_lease.py:reserve_node

    The outputted notebook will have a Markdown cell with the function's
    docstring, while the source of the function will be included in to a
    following code cell.

    Multiple examples can be provided, in which case the outputted Notebook
    file will have multiple code and markdown cells.
    """
    generate(examples, output_file=output_file, title=title)


if __name__ == '__main__':
    cli()
