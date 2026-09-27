The CHAVI client documentation is written using Sphinx.

The documentation is styled with a custom theme in `docs/_themes/chavi/` that matches the application's look (see `docs/ui-styleguide.md`). The theme is plain CSS plus a small layout template — edit `static/css/chavi.css` there to change colors.

The following steps are needed to build the documentation:

1. Ensure that Sphinx and its dependancies are installed. These can be installed by running the command `pip install -r requirements.txt`. Note that by default this would be done. 
2. Open the directory `docs` and run the command `make html` to build the documentation. The HTML files will be generated in the directory `docs/build/html`.

To add new documentation pages please add the new page to the `help_files` directory and then add the page to the `index.rst` file. 