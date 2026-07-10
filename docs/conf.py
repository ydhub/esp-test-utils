# Configuration file for the Sphinx documentation builder.
#
# For the full list of built-in configuration values, see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

import os
import sys

# Make the ``esptest`` package importable for autodoc without installing it.
sys.path.insert(0, os.path.abspath('..'))

# -- Project information -----------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#project-information

project = 'esp-test-utils'
copyright = '2024, Chen Yudong'
author = 'Chen Yudong'


def _get_version() -> str:
    try:
        from importlib.metadata import PackageNotFoundError, version

        return version('esp-test-utils')
    except (ImportError, PackageNotFoundError):
        return ''


release = _get_version()
version = release

# -- General configuration ---------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#general-configuration

extensions = [
    'sphinx.ext.autodoc',
    'sphinx.ext.autosummary',
    'sphinx.ext.viewcode',
    'sphinx.ext.napoleon',
    'sphinx.ext.intersphinx',
    'myst_parser',
]

# Use type hints from signature in parameter descriptions (avoids duplicating complex types in docstrings)
autodoc_typehints = 'description'
autodoc_member_order = 'bysource'
autodoc_default_options = {
    'members': True,
    'show-inheritance': True,
}
autosummary_generate = True

# Some autodoc imports pull in heavy or platform-specific dependencies. Mocking
# them keeps ``make html`` working on machines that lack every optional extra.
autodoc_mock_imports = [
    'pyecharts',
    'gitlab',
    'minio',
    'scapy',
    'usb',
    'pyudev',
    'esp_idf_monitor',
]

# MyST (Markdown) configuration.
myst_enable_extensions = [
    'colon_fence',
    'deflist',
]
myst_heading_anchors = 3

# Allow both reStructuredText and Markdown source files.
source_suffix = {
    '.rst': 'restructuredtext',
    '.md': 'markdown',
}

templates_path = ['_templates']
exclude_patterns = ['_build', 'Thumbs.db', '.DS_Store']

intersphinx_mapping = {
    'python': ('https://docs.python.org/3', None),
}


# -- Options for HTML output -------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#options-for-html-output

html_theme = 'sphinx_rtd_theme'
html_static_path = ['_static']
