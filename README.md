# Overview

tl;dr: A Python utility (db_read.py) that finds source filepaths for scenes in SmartEdit Writer project(s).

Longer: [SmartEdit Writer](https://smart-edit.com/) is a novel writing software; text in SmartEdit Writer is broken down into "scenes". When you create a scene in the SmartEdit Writer GUI, a .docx file is written to the file system (in the project's `Documents/` directory) with the scene's content. The .docx's filenames are integers (1.docx, 2.docx, etc.); there is no obvious mapping between scenes and their corresponding integer filenames, and the GUI provides no means to determine a scene's source .docx on the file system. This utility finds that mapping: It opens a SmartEdit Writer project's sqlite db, determines the mapping between scenes and their source files, and displays this info to the user (either on stdout, or in a generated .HTML file).

# Dependencies

- Windows OS
- python 3
- virtualenv python lib

# Quickstart

```
git clone https://github.com/bkuz114/SmartEdit-filepath-finder.git --recursive && cd SmartEdit-filepath-finder
virtualenv myenv && source ./myenv/Scripts/activate && pip install -r requirements.txt
python db_read.py
```

This is the most basic usage; it will search for all SmartEdit Writer projects on your system and prompt you to select one. Then it will determine the scene / source file mapping and display it for you on stdout.

![example](assets/images/db_read_example.png)

## Options for db_read.py

Usage:

`python db_read.py [--project PROJECT] [--short] [--remove] [--html]`

Options:

`--project PROJECT`

_Optional_. Absolute path to the SmartEdit Writer project that you want to find the source file mapping for. If not given, the tool will search for all SmartEdit Writer projects on the file system and prompt you to select one (see '--root' option below)

`--html`

_Optional, defaults to False__. Generate an HTML file with the scene / source file mapping, and open it in the default browser. (Else, the mapping will display on stdout)

`--short`

_Optional, defaults to False__. When displaying the scene / source file mapping, only display the names of the source files -- not their absolute paths.

`--remove`

_Optional, defaults to False__. Don't display the project name in the displayed tree.
