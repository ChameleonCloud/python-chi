import os
import sys

sys.path.insert(0, os.path.abspath(".."))

project = "python-chi"
copyright = "2021, University of Chicago"
author = "Jason Anderson"

version = "0.1"
release = "0.1"

extensions = [
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

html_theme = "furo"

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
    (
        master_doc,
        "ChameleonCloudPythonAPI.tex",
        description,
        "Nick Timkovich",
        "manual",
    ),
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
