import os
import sys

sys.path.insert(0, os.path.abspath(".."))

project = "python-chi"
copyright = "2021, University of Chicago"
author = "Jason Anderson"

version = "0.1"
release = "0.1"

extensions = [
    "nbsphinx",
    "sphinx.ext.autodoc",
    "sphinx.ext.intersphinx",
    "sphinx.ext.napoleon",
    "sphinx.ext.viewcode",
]

templates_path = ["_templates"]

source_suffix = [".rst"]

master_doc = "index"

exclude_patterns = ["build"]

# The name of the Pygments (syntax highlighting) style to use.
pygments_style = "sphinx"


# -- Options for HTML output -------------------------------------------------

html_theme = "sphinx_rtd_theme"
html_static_path = ["_static"]
html_extra_path = ["_extra"]

# Custom sidebar templates, must be a dictionary that maps document names
# to template names.
#
# The default sidebars (for documents that don't match any pattern) are
# defined by theme itself.  Builtin themes are using these templates by
# default: ``['localtoc.html', 'relations.html', 'sourcelink.html',
# 'searchbox.html']``.
#
# html_sidebars = {
#     '**': [
#         'about.html',
#         'navigation.html',
#         'relations.html',
#         'searchbox.html',
#     ],
# }

# Output file base name for HTML help builder.
htmlhelp_basename = "ChameleonCloudPythonAPI"

description = "Chameleon Cloud Python API"

# (source start file, target name, title,
#  author, documentclass [howto, manual, or own class]).
latex_documents = [
    (master_doc, "ChameleonCloudPythonAPI.tex", description, "Nick Timkovich", "manual"),
]

# (source start file, name, description, authors, manual section).
man_pages = [(master_doc, "chameleoncloudapi", description, [author], 1)]

# (source start file, target name, title, author,
#  dir menu entry, description, category)
texinfo_documents = [
    (
        master_doc,
        "ChameleonCloudPythonAPI",
        description,
        author,
        "ChameleonCloudPythonAPI",
        "A set of Python abstractions for interfacing with the Chameleon testbed",
        "Miscellaneous",
    ),
]

intersphinx_mapping = {
    "python3": ("https://docs.python.org/3/", None),
    "python37": ("https://docs.python.org/3.7/", None),
    "MySQLdb": ("https://mysqlclient.readthedocs.io/", None),
    "novaclient": ("https://docs.openstack.org/python-novaclient/latest/", None),
}

notebook_examples = [
    ('Making a reservation', 'notebooks/reservations.ipynb', [
        'tests/test_lease.py:example_reserve_node',
        'tests/test_lease.py:example_reserve_floating_ip',
        'tests/test_lease.py:example_reserve_network',
        'tests/test_lease.py:example_reserve_multiple_resources',
    ]),
    ('Launching a bare metal instance', 'notebooks/baremetal.ipynb', [
        'tests/test_server.py:example_create_server',
    ]),
]

nbsphinx_execute = 'never'
# This is processed by Jinja2 and inserted before each notebook
nbsphinx_prolog = r"""
{% set docname = env.doc2path(env.docname, base=None) %}

.. figure:: https://img.shields.io/badge/Chameleon-Open%20Notebook-brightgreen
   :target: https://jupyter.chameleoncloud.org/hub/import?deposition_repo=http&deposition_id=https://python-chi.readthedocs.io/en/latest/{{ docname|e }}&ephemeral=true

"""

import generate_notebook
for title, file, examples in notebook_examples:
    generate_notebook.generate(examples, output_file=file, title=title)
    # Also copy to the extras folder
    generate_notebook.generate(examples, output_file=f'_extras/{file}', title=title)
