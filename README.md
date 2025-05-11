# Overview

tl;dr: Python utility to finds source filepath for scenes in SmartEdit Writer project(s).

Longer: [SmartEdit Writer](https://smart-edit.com/) (SEW) is a novel writing software; content is stored in "scenes". When you create a scene in the SmartEdit Writer GUI, a .docx file is written to the file system with the scene's content. The .docx's filenames are integers (1.docx, 2.docx, etc.); there is no obvious mapping between scenes and the integer filename, and the GUI provides no means to determine a scene's source .docx on the file system. This utility finds that mapping: It opens a SmartEdit Writer project's sqlite db, and determines the mapping between scenes and their source files and displays this info to the user.

# Dependencies

- python 3
- virtualenv python lib

# Quickstart

```
git clone https://github.com/bkuz114/SmartEdit-filepath-finder.git --recursive && cd SmartEdit-filepath-finder
virtualenv myenv && source ./myenv/Scripts/activate && pip install -r requirements.txt
python db_read.py
```
