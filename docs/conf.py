# Configuration file for the Sphinx documentation builder.
#
# For the full list of built-in configuration values, see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

# -- Project information -----------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#project-information

import os
import sys
import django

sys.path.insert(0, os.path.abspath('..'))
os.environ['DJANGO_SETTINGS_MODULE'] = 'chavi_client.settings'
django.setup()



project = 'CHAVI Client'
copyright = '2025, Tata Medical Center'
author = 'Tata Medical Center'
release = '1.0'

# -- General configuration ---------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#general-configuration

extensions = [
    'sphinx.ext.autodoc',
    'sphinx.ext.viewcode',
    'sphinx.ext.napoleon',
]

templates_path = ['_templates']
exclude_patterns = ['_build', 'Thumbs.db', '.DS_Store']



# -- Options for HTML output -------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#options-for-html-output

# Custom CHAVI theme — palette and chrome per docs/ui-styleguide.md
html_theme = 'chavi'
html_theme_path = ['_themes']
html_static_path = ['_static']

# Sidebar: search first, then the full page tree, then prev/next links.
html_sidebars = {
    '**': ['searchbox.html', 'globaltoc.html', 'relations.html', 'sourcelink.html'],
}

html_title = 'CHAVI Client Documentation'
html_show_sphinx = False
