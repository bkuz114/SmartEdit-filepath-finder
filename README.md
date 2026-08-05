# Overview

tl;dr: A Python utility (db_read.py) that finds source filepaths for scenes in SmartEdit Writer project(s).

Longer: [SmartEdit Writer](https://smart-edit.com/) is a novel writing software; text in SmartEdit Writer is broken down into "scenes". When you create a scene in the SmartEdit Writer GUI, a .docx file is written to the file system (in the project's `Documents/` directory) with the scene's content. The .docx's filenames are integers (1.docx, 2.docx, etc.); there is no obvious mapping between scenes and their corresponding integer filenames, and the GUI provides no means to determine a scene's source .docx on the file system. This utility finds that mapping: It opens a SmartEdit Writer project's sqlite db, determines the mapping between scenes and their source files, and displays this info to the user (either on stdout, or in a generated .HTML file).

# Dependencies

- Windows OS
- BeautifulSoup 4.13.3 (installed via `requirements.txt`)
- Python 3.7+

# Quickstart

```
git clone https://github.com/bkuz114/SmartEdit-filepath-finder.git --recursive && cd SmartEdit-filepath-finder
pip install -r requirements.txt
python db_read.py
```

This is the most basic usage; it will search for all SmartEdit Writer projects rooted in your `Documents` folder and prompt you to select one. Then it will determine the scene / source file mapping and display it for you on stdout. (Note: to change the search root, supply `--search-root`. Alternatively, to specify a specific SmartEdit project, use `--project`.)

![example](assets/images/db_read_example.png)

**HTML Report**

To display the database mapping in a static HTML report, supply the `--html` option.

## Options for db_read.py

Usage:

`python db_read.py [--project PROJECT...] [--search-root PATH] [--norecursive] [--short] [--remove] [--html] [--merge] [--browser] [--output PATH] [--force] [--force-assets] [--nuclear]`

Options:

`--project PROJECT`, `-p PROJECT`

_Optional_. Absolute or relative path to one or more SmartEdit Writer projects. Can be supplied multiple times (e.g. `-p proj1 -p proj2`). If not given, the tool will search for all SmartEdit Writer projects rooted in the user's Documents folder (or `--search-root` if supplied) and prompt you to select one or more.

`--search-root PATH`

_Optional_. Directory to search for SmartEdit Writer projects when `--project` is not supplied. Defaults to the user's Documents folder. Ignored if `--project` is given.

`--norecursive`

_Optional, defaults to False_. When searching for SmartEdit Writer projects (i.e. `--project` is not supplied), limit the search to the top-level directory only. Speeds up the search but may miss projects nested in subdirectories.

`--short`, `-s`

_Optional, defaults to False_. When displaying the scene / source file mapping, only display the filenames of the source files — not their absolute paths.

`--remove`, `-r`

_Optional, defaults to False_. Don't display the project name in the tree. Useful when the project name is obvious from context or unwanted in the output.

`--html`

_Optional, defaults to False_. Generate an HTML report with the scene / source file mapping. Without this flag, the mapping displays on stdout. By default, a separate report is generated for each project in the current working directory, named after the project (e.g. `My Novel.html`). Use `--merge` to combine all projects into a single report, written to `./report.html` unless `--output` is supplied.

`--merge`

_Optional, defaults to False_. Combine all selected projects into a single HTML report. Without this flag, each project generates its own report file. Requires `--html`.

`--browser`

_Optional, defaults to False_. Open the generated HTML report(s) in the default browser upon completion. Requires `--html`.

`--output PATH`

_Optional_. When `--merge` is supplied, this is the output file path (default: `./report.html`). When `--merge` is not supplied, this is the output directory where per-project reports are written (default: current working directory). Requires `--html`. Relative paths are resolved relative to the current working directory.

`--force`

_Optional, defaults to False_. Overwrite the HTML report file if it already exists. If the report exists and `--force` is not supplied, the script will exit with an error.

`--force-assets`

_Optional, defaults to False_. Overwrite the assets/ directory (CSS, JS, favicon) at the output location if it already exists. If the assets/ directory exists and `--force-assets` is not supplied, the copy is skipped and existing assets are used as-is — this preserves any user customizations. Separate from `--force` so you can refresh the report without nuking custom CSS or JS.

`--nuclear`

_Optional, defaults to False_. USE AT YOUR OWN RISK. Force-deletes the assets/ directory at the output location by stripping read-only permissions before retrying. Only needed on Windows when `--force-assets` fails with "Access is denied" errors (caused by antivirus, search indexer, or Explorer holding transient file locks).

### Interactive Project Selection

When `--project` is not supplied, the script searches for SmartEdit Writer projects and presents a numbered list. You can select projects by:

  - A single number: `3`
  - A comma-separated list: `1,3,4`
  - A range (inclusive): `4-7`
  - Mixed: `2,4-7,9`
  - `all` to select every discovered project
  - `0` to exit

### HTML Report Assets

The generated HTML report is fully self-contained. When `--html` is used, the script automatically copies the required assets (CSS, JavaScript, favicon) alongside the report. No manual setup is required.

For reference, the asset directory structure:

    assets/
    ├── css/
    │   └── style.css
    ├── js/
    │   └── scripts.js
    └── images/
        └── favicon.ico
