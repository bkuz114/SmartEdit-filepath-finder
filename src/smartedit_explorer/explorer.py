"""
Finds the source files for scenes in a SmartEdit Writer project
and displays them either on stdout or in an HTML file.

Usage:
    python explorer.py [--project PROJECT] [--short] [--html]

    --project PROJECT:
        abs path to a SmartEdit Writer Project
        if not supplied, finds all projects by recursively
        searching the user's Documents folder and asks
        you to select one
    --short:
        print only filenames of scene (not full abs path)
    --html:
        generate an HTML file with a table of data,
        rather than printing it to stdout
"""

import sys
import os
import re
import random
import unicodedata
import argparse
import webbrowser
import json
import sqlite3
import shutil
import copy
import stat
import string
from bs4 import BeautifulSoup
from pathlib import Path
from datetime import datetime, timezone

# (lib for parsing .toml script config file)
# tomli is a backport for Python < 3.11.
# On Python 3.11+, the stdlib tomllib should be used:
try:
    import tomllib
except ImportError:
    import tomli as tomllib

# Allow direct execution from source during development (e.g., `python explorer.py`)
# by adding the `src/` directory to Python's import path. This block only runs
# when the script is executed directly, not when imported as a module or run
# from a pip installation.
if __name__ == "__main__":
    # get src dir to add to python path
    src_dir = Path(__file__).resolve().parent.parent  # resolve() to handle symlinks
    if str(src_dir) not in sys.path:
        sys.path.insert(1, str(src_dir))

# vendored packages
from smartedit_explorer.vendor import beautiful_soup_utils

# version string to use for --version option (comes from __init__.py)
from smartedit_explorer import __version__

# set up template and assets defaults within the pip project
import smartedit_explorer

# Get the package root directory using __file__.
#
# Why not importlib.resources?
#   On Windows, importlib.resources returns a MultiplexedPath object that
#   cannot be converted to a real Path without ugly string hacks. The
#   __file__ approach is simpler and works reliably because setuptools
#   guarantees that package data (templates, assets) are installed to the
#   filesystem alongside the package.
#
# Assumption:
#   This assumes the package is installed to a filesystem directory
#   (not a zip file). For a CLI tool distributed via PyPI, this is true
#   for all normal installation methods (pip, pipx, etc.).
#
# Package structure expected:
#   smartedit_explorer/
#   ├── __init__.py
#   ├── explorer.py
#   └── assets/
#       ├── css/
#       └── js/
PACKAGE_ROOT = Path(smartedit_explorer.__file__).parent

# Verify the directory exists (helpful error if structure changes)
if not PACKAGE_ROOT.exists():
    raise RuntimeError(f"Package root not found at {PACKAGE_ROOT}")

# default path to look for script config file
# (can be overwritten with --config-file)
CONFIG_FILE_DEFAULT = Path.cwd() / "smartedit_explorer.toml"

TEMPLATES_DIR = PACKAGE_ROOT / "templates"
TEMPLATE = TEMPLATES_DIR / "template.html"
SOUP = BeautifulSoup("", "html.parser")

# ANSI escape sequences for stdout
BLACK = "\033[30m"
RED = "\033[31m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
BLUE = "\033[34m"
MAGENTA = "\033[35m"
CYAN = "\033[36m"
WHITE = "\033[37m"
BOLD = "\033[1m"
DIM = "\033[2m"
ITALIC = "\033[3m"
UNDERLINE = "\033[4m"
BLINK = "\033[5m"
REVERSE = "\033[7m"
HIDDEN = "\033[8m"
STRIKE = "\033[9m"
RESET = "\033[0m"

# Node attributes that can be sorted on via --sort
# These must attributes of the Node class!
SORT_KEYS = ["name", "date_modified", "type", "id", "position"]

# if user doesn't supply --project, will search
# for SmartEdit projects and prompt for user selection.
# SEARCH_ROOT is default location to start search in.
# Defaults to the user's Documents folder;
# modify this if your SmartEdit Writer projects
# are stored elsewhere
# (search root overridden via --search-root arg)
SEARCH_ROOT = Path.home() / "Documents"

# default directory for HTML reports (overridden by --output)
DEFAULT_HTML_REPORT_DIR = Path.cwd() / "reports"
# default filename for a single report (--merge arg)
DEFAULT_HTML_REPORT_FILENAME = "report.html"
# default directory name for converted source files (--convert arg)
DEFAULT_CONVERTED_DIRNAME = "html"
# default directory for converted source files (--convert arg)
DEFAULT_CONVERTED_DIR = DEFAULT_HTML_REPORT_DIR / DEFAULT_CONVERTED_DIRNAME
# default filename for JSON file (--json-out)
DEFAULT_JSON_FILENAME = "out.json"
# default path for JSON file (--json-out)
DEFAULT_JSON_FILE = DEFAULT_HTML_REPORT_DIR / DEFAULT_JSON_FILENAME
# source assets/ directory that static reports rely on
ASSETS_SRC = PACKAGE_ROOT / "assets"
# Directory containing CSS stylesheets for converted source files.
# Each .css file in this directory becomes a valid --style option
# (filename without extension = style name).
CONVERTED_CSS_DIR = ASSETS_SRC / "css" / "converted"

# Populate available styles from the filesystem.
# Keys are style names (filename stem), values are the CSS content
# read once at module load.
CONVERTED_STYLES = {}
if CONVERTED_CSS_DIR.is_dir():
    for css_file in sorted(CONVERTED_CSS_DIR.rglob("*.css")):
        style_name = css_file.stem.lower()  # filename without .css
        CONVERTED_STYLES[style_name] = css_file.read_text(encoding="utf-8")
# fail early if no default.css (should always be present for argparse default --style)
if "default" not in CONVERTED_STYLES:
    raise FileNotFoundError(
        f"(bug -- fix this): default.css not found in {CONVERTED_CSS_DIR}. "
        f"A default stylesheet is required for argparse --style to work."
    )

# CSS classes for icons to set as project tree roots
# (these classes should have corresponding rules in style.css)
TREE_ROOT_ICON_CLASSES = [
    "icon-blue",
    "icon-green",
    "icon-orange",
    "icon-red",
    "icon-ledger",
    "icon-notebook",
    "icon-decorative",
]


# ============================================================================
# NODE CLASS FOR TREE CONSTRUCTION
# ============================================================================


class Node:
    """
    A node in a SmartEdit Writer project tree.

    Represents any item in the project hierarchy: folders, scenes, notes,
    root nodes, etc. Children are maintained in Position order via
    add_child().

    Attributes:
        name (str): UserDefinedName from MetaData (display name in the UI).
        id (int): MetaData.ID (database primary key, also used for filenames).
        type (int): MetaData.ItemType (0=root, 1=folder, 2=scene, 3=note, etc.).
        section (int or None): MetaData.Section — the project section the
            item belongs to (1=Manuscript, 5=Fragments, 6=Research).
            None for synthetic nodes like the project root.
        depth (int): Distance from the tree root (0 for the root, increments
            by 1 for each level of children). Set automatically by
            add_child().
        date_modified (int or None): Unix epoch timestamp of the item's
            last modification, or None if not set (e.g., for folders
            and root nodes which have no modification date in the
            database).
        position (int): DisplayTrees.Position (ordinal among siblings).
        source (Path or None): Path to the on-disk file, or None if not file-backed.
        parent (Node or None): Parent Node, or None for the root.
        children (list[Node]): List of child Nodes, maintained in Position order.
    """

    # Registry of known item types and their display properties.
    # (where item type is the value of the ItemType col in the MetaData table
    # of the SmartEdit Writer SQLite database for the project the Node
    # belongs to)
    # Each entry maps a MetaData.ItemType value to its name, icon, CSS class,
    # file extension, and on-disk directory. All Node behavior that varies by
    # type (is_file_backed, icon, css_class, extension) derives from this
    # registry. Add new types here to support additional SmartEdit Writer
    # item types.
    _TYPE_REGISTRY = {
        None: {
            # Synthetic root created by db_info() to hold all section trees.
            # Not stored in the SmartEdit Writer database.
            "name": "project",
            "icon": "📚",
            "css": "",
            "file_ext": None,
            "directory": None,
            "file_backed": False,
        },
        0: {
            # Database root node (ItemType=0). One per section in the project
            # (e.g., Manuscript, Fragments, Research). Has a row in MetaData
            # and DisplayTrees; rendered as a collapsible section header.
            "name": "root",
            "icon": "📚",
            "css": "",
            "file_ext": None,
            "directory": None,
            "file_backed": False,
        },
        1: {
            "name": "folder",
            "icon": "📁",
            "css": "folder-node",
            "file_ext": None,
            "directory": None,
            "file_backed": False,
        },
        2: {
            "name": "scene",
            "icon": "📄",
            "css": "scene-node",
            "file_ext": "docx",
            "directory": "Documents",
            "file_backed": True,
        },
        3: {
            "name": "note",
            "icon": "🗒️",
            "css": "note-node",
            "file_ext": "rtf",
            "directory": "Documents",
            "file_backed": True,
        },
        6: {
            "name": "file",
            "icon": "🖼️",
            "css": "file-node",
            # ItemType 6 covers user-attached files (images, PDFs, etc.). Unlike
            # scenes and notes, the file extension is not fixed — it depends on
            # what the user attached. Extension must be resolved at runtime via
            # get_files_extension(), which queries the Files table in a project
            # Sqlite DB using the item's MetaData.ID.
            "file_ext": None,
            "directory": "Files",
            "file_backed": True,
        },
    }

    _SECTION_REGISTRY = {
        5: {
            "name": "fragments",
            "icon": "🗃️",
            "css": "fragments-section-node",
        },
        6: {
            "name": "research",
            "icon": "🔬",
            "css": "research-section-node",
        },
    }

    def __init__(
        self,
        name,
        id,
        type,
        section,
        depth=0,
        date_modified=None,
        position=0,
        source=None,
        parent=None,
        is_section_root=False,
    ):
        self.name = name
        self.id = id
        self.type = type
        self.section = section
        self.depth = depth
        self.date_modified = date_modified
        self.position = position
        self.source = source
        self.parent = parent
        self.children = []
        self.is_section_root = is_section_root

    # --- Static methods: query type info without a Node instance ---

    @staticmethod
    def get_extension(item_type):
        """Return the file extension for a given ItemType, or None if not file-backed."""
        return Node._TYPE_REGISTRY.get(item_type, {}).get("file_ext")

    @staticmethod
    def get_file_backed_types():
        """Return a list of ItemType values that correspond to files on disk."""
        # returns a list of top level keys (e.g. item types)
        # if the dict they map to has a valid file_ext key
        return [
            item_type
            for item_type, props in Node._TYPE_REGISTRY.items()
            if props.get("file_backed")
        ]

    @staticmethod
    def is_file_backed_type(item_type):
        """Return True if the given ItemType corresponds to a file on disk."""
        return item_type in Node.get_file_backed_types()

    @staticmethod
    def get_directory(item_type):
        """Return the on-disk directory for a given ItemType, or None."""
        return Node._TYPE_REGISTRY.get(item_type, {}).get("directory")

    @staticmethod
    def get_icon_type(item_type):
        """Return the emoji icon for a given ItemType, or "" if unknown."""
        return Node._TYPE_REGISTRY.get(item_type, {}).get("icon", "")

    @staticmethod
    def get_icon_section(item_section):
        """Return the emoji icon for a given ItemSection, or "" if unknown."""
        return Node._SECTION_REGISTRY.get(item_section, {}).get("icon", "")

    @staticmethod
    def get_css_class_type(item_type):
        """Return CSS class for a given ItemType, or "" if none."""
        return Node._TYPE_REGISTRY.get(item_type, {}).get("css", "")

    @staticmethod
    def get_css_class_section(item_section):
        """Return CSS class for a given Section, or "" if none."""
        return Node._SECTION_REGISTRY.get(item_section, {}).get("css", "")

    # --- Instance properties: delegate to static methods using self.type ---

    @property
    def extension(self):
        """File extension for this node's type, or None."""
        return Node.get_extension(self.type)

    @property
    def is_file_backed(self):
        """True if this node's type corresponds to a file on disk."""
        return Node.is_file_backed_type(self.type)

    @property
    def directory(self):
        """On-disk directory for this node's type, or None."""
        return Node.get_directory(self.type)

    @property
    def icon(self):
        """Emoji icon for this node's type and section"""
        if self.is_section_root:
            return Node.get_icon_section(self.section)
        else:
            return Node.get_icon_type(self.type)

    @property
    def css_class(self):
        """CSS class for this node or "" """
        if self.is_section_root:
            return Node.get_css_class_section(self.section)
        else:
            return Node.get_css_class_type(self.type)

    @property
    def has_children(self):
        """bool: True if this node contains child nodes.

        Accurate only after tree construction is complete (i.e., after
        db_info() has returned). During the linking pass in db_info(),
        children may not yet be attached.
        """
        return bool(self.children)

    @property
    def is_leaf(self):
        """bool: True if this node has no children.

        Accurate only after tree construction is complete.
        """
        return not self.has_children

    @property
    def is_container(self):
        """bool: True if this node has children (inverse of is_leaf).

        Accurate only after tree construction is complete.
        """
        return self.has_children

    @property
    def is_root(self):
        """bool: True if this node has no parent (i.e., it is the root
        of its tree).

        Accurate only after tree construction is complete.
        """
        return self.parent is None

    @property
    def date_modified_display(self):
        """Return a human readable string for date modified"""
        if not self.date_modified:
            return None
        return datetime.fromtimestamp(self.date_modified, tz=timezone.utc).strftime(
            "%Y-%m-%d %H:%M:%S %Z"
        )

    def to_dict(self, short=False):
        """Return a dict representation of a Node

        Args:
            short (bool): if node has a souce file (Scenes, Notes, etc)
                return file in the dict rather than abs paths
        """
        source = None
        if self.source:
            source = str(self.source.name) if short else str(self.source)
        node_hash = {
            "name": self.name,
            "type": self.type,
            "id": self.id,
            "source": source,
            "children": [child.to_dict(short) for child in self.children],
        }
        modified = self.date_modified
        if modified:
            node_hash["modified"] = modified
        return node_hash

    def add_child(self, child, sort_by, sort_reverse):
        """Insert child and maintain sort order among siblings.

        Appends the child to this node's children list, sets its parent
        reference, updates its depth, and re-sorts all siblings by the
        given attribute and direction.

        Args:
            child (Node): The child Node to insert.
            sort_by (str): Name of the Node attribute to sort siblings by
                (e.g., "position", "name", "date_modified", "type").
            sort_reverse (bool): True sorts descending, False ascending.
                Passed to list.sort()'s reverse parameter.
        """
        child.parent = self
        child._update_depth(self.depth + 1)
        self.children.append(child)

        # -------------------------------------------------------------
        # Sort all children by sort_by attribute; None values sort last
        # -------------------------------------------------------------
        # The lamba key returns a tuple:
        #   (is_None, value)
        #   * The first element is True if the attribute is None, False otherwise.
        #   * The second element returns the actual attr
        #
        # - During the comparison sort, Python will compare items A and B
        #   by each of their tuple elements, in order
        # - Since False < True in Python, items with real values always sort
        #   before items with None.
        # - The second element (the actual value) is only compared when
        #   both items have values or both are None.
        #
        # This ensures None values consistently sort to the end (or the
        # beginning if reverse=True), regardless of the actual values.
        #
        # Example: sorting by date_modified
        #   Scene A (date=1700000000) -> (False, 1700000000)
        #   Scene B (date=1650000000) -> (False, 1650000000)
        #   Folder C (date=None)      -> (True,  None)
        #
        #   A vs B: False==False, compare dates -> B comes first
        #   B vs C: False < True       -> B comes before C
        #   Result: B, A, C  (None values at the end)
        self.children.sort(
            key=lambda n: (getattr(n, sort_by) is None, getattr(n, sort_by)),
            reverse=sort_reverse,
        )

    def _update_depth(self, depth):
        """Set this node's depth and recursively update all descendants."""
        self.depth = depth
        for grandchild in self.children:
            grandchild._update_depth(depth + 1)

    def __repr__(self):
        return (
            f"Node(name={self.name!r}, id={self.id}, type={self.type}, "
            f"depth={self.depth}, section={self.section}, "
            f"date_modified={self.date_modified}, "
            f"is_section_root={self.is_section_root}, "
            f"position={self.position}, children={len(self.children)})"
        )


def print_tree(node, indent=0):
    """
    Print a Node tree to stdout for debugging.

    Displays each node's name, type, position, and source file (if any)
    in an indented tree format. Children are printed in their stored order.

    Args:
        node (Node): Root Node of the tree (or subtree) to print.
        indent (int): Current indentation level (used internally for recursion).
    """
    spacer = "    " * indent

    # Determine icon for visual distinction
    icon = node.icon

    # Build the line: icon, name, metadata
    parts = [f"{spacer}{icon} {node.name}"]
    meta = []
    if node.id is not None:
        meta.append(f"id={node.id}")
    if node.type is not None:
        meta.append(f"type={node.type}")
    meta.append(f"pos={node.position}")
    if node.date_modified:
        meta.append(f"modified={node.date_modified_display}")
    if node.source is not None:
        meta.append(f"source={node.source.name}")
    if meta:
        parts.append(f"  ({', '.join(meta)})")

    print("".join(parts))

    for child in node.children:
        print_tree(child, indent + 1)


# ============================================================================
# GENERAL UTILITY FUNCTIONS
# ============================================================================


def filetime_to_epoch(ft):
    """
    Convert a Windows FILETIME timestamp to Unix epoch seconds.

    Windows FILETIME is the number of 100-nanosecond intervals since
    1601-01-01 00:00:00 UTC. This function converts it to Unix epoch
    time (seconds since 1970-01-01 00:00:00 UTC), which can be passed
    to datetime.fromtimestamp() for human-readable formatting or used
    directly for sorting and comparison.

    Args:
        ft (int): Windows FILETIME value, or None/0 if not set.

    Returns:
        float or None: Unix epoch time in seconds, or None if the
        input is falsy (None, 0, or empty).
    """
    if not ft:
        return None
    # FILETIME epoch (1601-01-01) to Unix epoch (1970-01-01) in seconds
    EPOCH_DIFF = 11644473600
    return int(ft / 10000000 - EPOCH_DIFF)


def display_width(text):
    """
    Return the number of terminal columns a string occupies
    (i.e. the true width it displays in the terminal), so you
    can accurately compare how two strings will display and align
    them in stdout output.

    Python strings are sequences of Unicode code points — the
    atomic units that identify characters. For example, "📄" is
    one code point (U+1F4C4, PAGE FACING UP). "🗒️" is two code
    points: the base character 🗒 (U+1F5D2, SPIRAL NOTE PAD)
    followed by ️ (U+FE0F, VARIATION SELECTOR-16), which tells
    the terminal to use emoji presentation for the preceding
    character.

    A terminal displays text in a grid of columns. How many
    columns a code point occupies depends on what it represents.
    Most Latin letters and symbols occupy 1 column. Many emojis
    and CJK characters occupy 2 columns. Some characters occupy
    0 columns — they are invisible, like the variation selector
    U+FE0F. A small number of characters occupy more than 2
    columns.

    Python's built-in len() counts code points. The problem is
    that code points and columns don't always match. Two strings
    with the same len() can occupy different numbers of columns
    in the terminal, so they won't line up even though len()
    says they should. For example:

    - "📄": len()=1, occupies 2 columns
    - "a":  len()=1, occupies 1 column

    These two strings have the same len(), but appear to have
    different widths when printed.

    This function counts columns, not code points, so you can
    compare how two strings will display in the terminal.

    Args:
        text (str): The string to measure.

    Returns:
        int: The number of terminal columns the string occupies.

    Examples:
        # "a": 1 code point (len() returns 1), dsplays across 1 column
        >>> display_width("a")
        1

        # "📄": 1 code point (len() returns 1), displays across 2 columns
        >>> display_width("📄")
        2

        # "🗒️": 2 code points (🗒 + invisible ️), displays across 2 columns
        >>> display_width("🗒️")
        2
    """
    # Unicode general categories that are always zero-width:
    #   Mn = Non-Spacing Mark (e.g., variation selectors like U+FE0F,
    #        which modify the previous character's presentation without
    #        taking up space)
    #   Cf = Format Character (e.g., zero-width joiners like U+200D
    #        used in compound emojis, zero-width spaces)
    #   Zl = Line Separator (zero-width)
    #   Zp = Paragraph Separator (zero-width)
    # Excluded: Cc (includes tab), Mc/Me (combining marks that can have width)
    _ZERO_WIDTH = frozenset({"Mn", "Cf", "Zl", "Zp"})

    width = 0
    for char in text:
        if unicodedata.category(char) in _ZERO_WIDTH:
            continue  # zero-width, doesn't affect the column count

        # East Asian Width classifications:
        #   F = Fullwidth (2 columns)
        #   W = Wide (2 columns, e.g., CJK ideographs, many emojis)
        # (Note: A (ambiguous) can be 1 or 2 cols, but typically
        #  1 in Latin and Cryillic terminal contexts so not including)
        if unicodedata.east_asian_width(char) in "FW":
            width += 2
        else:
            width += 1
    return width


def generate_random_alphanumeric(length):
    """
    Generate a random string of alphanumeric characters.

    Used as a fallback when safe_name() is given a string with no
    alphanumeric content and cannot produce a meaningful name.

    Args:
        length (int): number of characters in the returned string

    Returns:
        str: a random string of letters and digits
    """
    characters = string.ascii_letters + string.digits
    return "".join(random.choice(characters) for _ in range(length))


def safe_name(name):
    """
    Sanitize a string for use as a filesystem directory or filename.

    Replaces any character that is not a word character (\w: letters,
    digits, or underscore), regardless of language, with an underscore,
    collapses consecutive underscores into a single one, and strips
    leading and trailing underscores. If the result is empty or would
    be just underscores (i.e. the input contained no alphanumeric
    characters at all), returns a random 4-character alphanumeric
    string as a fallback.

    This produces names that are safe across platforms without being
    overly restrictive — spaces, punctuation, and Unicode are replaced
    rather than removed, preserving word boundaries and approximate
    readability.

    Args:
        name (str): the original string (e.g. a project name)

    Returns:
        str: a sanitized version suitable for directory names

    Examples:
        >>> safe_name("My Novel (2024)")
        "My_Novel_2024"
        >>> safe_name("!!!")
        "a3k9"   # random fallback
    """

    def name_fallback():
        return generate_random_alphanumeric(4)

    # corner case: name is None
    if not name:
        return name_fallback()
    # convert anything that isn't a letter, digit, or _ to _
    # UNICODE flag extends \w to match letters/digits from
    # any script (Cyrillic, etc.), not just ASCII
    name = re.sub(r"[^\w]", "_", name, flags=re.UNICODE)
    # collapse all _ to a single _
    name = re.sub(r"_+", "_", name)
    # corner case: only _ remains (there were no alpha-numeric)
    if name == "_":
        return name_fallback()
    # remove leading and trailing _
    name = name.strip("_")
    return name


def is_integer(string_to_check):
    """Checks if a string can be parsed into an integer"""
    try:
        int(string_to_check)
        return True
    except (ValueError, TypeError):
        return False


def same_path(path1, path2):
    """
    Return True if two Paths refer to the same filesystem location.

    Assumes the paths might not exist, so symlinks and case sensitivity
    are resolved as far as possible without failing.

    Args:
        path1 (Path): First Path
        path2 (Path): Second Path

    Returns:
        bool: True if same, else False
    """
    # strict=False resolves symlinks and case sensitivity as far as possible without
    # failing if the Path doesn't exist
    return Path(path1).resolve(strict=False) == Path(path2).resolve(strict=False)


def make_path_writable(function, path, excinfo=None):
    """Make a path writable and retry the function."""
    os.chmod(path, stat.S_IWRITE)
    function(path)


def remove_path(path: Path, force: bool, nuclear: bool) -> None:
    """Remove a path, optionally handling Windows read-only attributes.

    Args:
        path: The path to remove.
        force: If False, raises FileExistsError when the path exists.
               If True, attempts normal deletion via shutil.rmtree.
        nuclear: If True, uses aggressive deletion that strips read-only
                 permissions before retrying (Windows only). Implies force.

    Returns:
        None

    Raises:
        FileExistsError: If force and nuclear are both False and path exists.
        RuntimeError: If deletion fails after attempting force or nuclear
            strategies.

    Notes:
        The nuclear option is a Windows-specific workaround for `[WinError 5] Access is denied`
        errors that occur even when the path is deletable via Explorer. It applies
        `os.chmod(path, stat.S_IWRITE)` to any item that fails deletion and retries.

        Use nuclear only as a last resort when standard --force fails with permission errors.
    """
    if not path.exists():
        return

    try:
        if nuclear:
            shutil.rmtree(path, onerror=make_path_writable)
        elif force:
            shutil.rmtree(path)
        else:
            raise FileExistsError(
                f"Path already exists: {path}\nUse force=True to overwrite."
            )
    except Exception as e:
        raise RuntimeError(f"Failed to remove path. Error: {e}")


# ============================================================================
# SMARTEDIT WRITER PROJECT DISCOVERY
# ============================================================================


def find_projects(search_root, recursive):
    """
    find all SmartEdit Writer projects
    on the file system

    Args:
        search_root (Path): root directory to begin searching for SmartEdit Writer projects
        recursive (bool): do a recursive search for SmartEdit projects.

    Returns:
        list[Path]: list of abs paths to SmartEdit Writer projects found
    """
    result = []
    for root, dirs, files in os.walk(search_root):
        if "atomic.scribbler" in files:
            proj_path = search_root / root
            result.append(proj_path)
        if not recursive:
            dirs.clear()  # don't descend into subdirectories
    return result


def get_selections(selection_str):
    """
    Parse a project selection string into a deduplicated list of
    integer indices (1-based), collecting all errors.

    Supports:
      - Single numbers: "3"
      - Comma-separated list: "1,3,4"
      - Ranges: "4-7" (inclusive)
      - Mixed: "2,4-7,9"

    Args:
        selection_str (str): raw input string from the user

    Returns:
        tuple[list[int], list[str]]: (selections, errors) where
            selections is a list of valid parsed indices and errors is a
            list of error messages for invalid parts
    """
    selections = []
    errors = []
    parts = [p.strip() for p in selection_str.split(",")]

    for part in parts:
        if "-" in part:
            range_parts = part.split("-", 1)
            start_str, end_str = range_parts[0].strip(), range_parts[1].strip()

            if not is_integer(start_str) or not is_integer(end_str):
                errors.append(f"Invalid range: '{part}' (non-numeric)")
                continue

            start, end = int(start_str), int(end_str)
            if start > end:
                errors.append(f"Invalid range: {start}-{end} (start > end)")
                continue

            selections.extend(range(start, end + 1))
        else:
            if not is_integer(part):
                errors.append(f"Invalid selection: '{part}' (not a number)")
                continue
            selections.append(int(part))

    # Deduplicate while preserving order
    selections = list(dict.fromkeys(selections))

    return selections, errors


def chose_projects(projects):
    """
    displays a numbered list of SmartEdit Writer projects
    and prompts user to select one or more, then returns
    selected projects

    (see get_selections for list of valid selection syntax)

    Args:
        projects (list[Path]): list of abs filepaths to SmartEdit Writer
            projects to display to the user.

    Returns:
        list[Path]: abs path to the selected SmartEdit Writer projects
    """
    for idx, project in enumerate(projects):
        print(f"[{idx + 1}] : {project}")
    while True:
        selection = input(
            f"\nPlease select a project 1 - {len(projects)}, a comma separated list (e.g. 1,3,4), or all to select all. (Enter 0 to exit): "
        )

        # if 0, exit
        if selection.strip() == "0":
            sys.exit(0)

        if selection.strip().lower() == "all":
            return projects

        # get project number selections
        selections, parse_errors = get_selections(selection)
        if parse_errors:
            for err in parse_errors:
                print(f"  - {err}")
            continue

        # alert user of any incorrect project selections
        invalid = [i for i in selections if i < 1 or i > len(projects)]
        if invalid:
            invalid_str = ", ".join([str(i) for i in invalid])
            plural = "s" if len(invalid) > 1 else ""
            print(
                f"\nInvalid selection{plural} entered: {invalid_str}. Valid project numbers: (1 - {len(projects)})"
            )
        else:
            return [projects[int(i) - 1] for i in selections]


def get_projects_interactively(search_root, recursive):
    """
    Finds all SmartEdit Writer projects on the file
    system and prompts user to select one or more.

    Args:
        search_root (Path): root directory to begin searching for SmartEdit Writer projects
        recursive (bool): do a recursive search for SmartEdit projects.

    Returns:
        tuple of (all_projects, selected_projects) where:
        - all_projects: list[Path] — all SmartEdit Writer projects
          found on the system
        - selected_projects: list[Path] — the projects chosen by
          the user from the interactive prompt
    """
    print("\nfinding SmartEdit Writer projects...\n", flush=True)
    projects = find_projects(search_root, recursive)
    if not projects:
        print(
            f"No SmartEdit projects could be found in {search_root}! (Try supplying --search-root to specify a search root, or omitting --no-recursive, to allow for a recursive search)"
        )
        sys.exit(1)
    chosen = chose_projects(projects)
    return projects, chosen


# ============================================================================
# SCENE MAPPING (SQLITE DATABASE)
# ============================================================================


def db_info(proj_path, sort_by, sort_reverse):
    """
    Build a tree of Node objects representing the project structure.

    Queries all sections (Manuscript, Fragments, Research) and
    assembles them under a synthetic project root. Manuscript items
    appear directly under the project root for immediate access;
    Fragments and Research appear as named folder nodes at the bottom
    of the tree.

    Args:
        proj_path (Path): Absolute path to the SmartEdit Writer project
            directory (the parent of .atomic and Documents).
        sort_by (str): Name of the Node attribute to sort children by.
        sort_reverse (bool): True sorts descending, False ascending.
            Passed to list.sort()'s reverse parameter.

    Returns:
        Node: The root node of the project tree.
    """
    db_path = proj_path / ".atomic" / "atomic.meta"  # project db

    con = sqlite3.connect(str(db_path))
    cur = con.cursor()

    # Create the synthetic project root
    project_name = get_project_name(cur)
    root = Node(
        name=project_name, id=None, type=None, section=None, depth=0, position=0
    )

    # Section config: (section_number, display_name)
    # display_name=None means children are inlined directly under the
    # project root. Otherwise, a folder node is created with that name.
    sections = [
        (1, None),  # Manuscript — inline children
        (5, "Fragments"),  # Fragments — wrapped in a folder
        (6, "Research"),  # Research — wrapped in a folder
    ]

    # Sections are processed in display order. Manuscript children are added
    # as top level notdes, then Fragments, then Research as siblings. Use a
    # running position counter so each section's folder sorts after the previous one.
    next_position = 0

    for section, display_name in sections:
        # get tree for this section.
        # will return the entire tree including its root
        # want to strip out that root and make our own,
        # or add the root's children directly for main manuscript
        section_root = get_section(cur, section, proj_path, sort_by, sort_reverse)

        if display_name is None:
            # Manuscript: add its children directly under the project root
            for child in section_root.children:
                root.add_child(child, sort_by, sort_reverse)
            # Update the counter to sort next section after manuscript items
            if section_root.children:
                next_position = (
                    max(child.position for child in section_root.children) + 1
                )
        else:
            # Fragments / Research: wrap children in a named folder node
            folder = Node(
                name=display_name,
                id=None,
                type=1,
                section=section,
                position=next_position,
                is_section_root=True,
            )
            for child in section_root.children:
                folder.add_child(child, sort_by, sort_reverse)
            root.add_child(folder, sort_by, sort_reverse)
            next_position += 1

    # close connections
    cur.close()
    con.close()

    return root


def get_section(cur, section, proj_path, sort_by, sort_reverse):
    """
    Build a tree of Node objects for a single section of a SmartEdit
    Writer project.

    Queries MetaData and the appropriate tree table (DisplayTrees for
    sections 1 and 5, ResearchTree for section 6) to construct the
    full hierarchy for the given section. Children are ordered by
    Position, matching the SmartEdit Writer UI.

    Args:
        cur (sqlite3.Cursor): Cursor for the project database.
        section (int): Section number (1=Manuscript, 5=Fragments,
            6=Research).
        proj_path (Path): Absolute path to the project directory.
        sort_by (str): Name of the Node attribute to sort children by.
        sort_reverse (bool): True sorts descending, False ascending.
            Passed to list.sort()'s reverse parameter.

    Returns:
        Node: The root node of the section tree, or None if the
            section has no items.
    """

    # Determine which tree table to query for this section
    # (Both fragments and main doc root are in DisplayTrees)
    tree_table = "DisplayTrees"
    if section == 6:
        tree_table = "ResearchTree"

    cur.execute(f"""
        SELECT m.ID, m.UserDefinedName, m.ItemType, m.DateModified, t.ParentId, t.Position
        FROM MetaData m
        JOIN {tree_table} t ON m.ID = t.ItemId
        WHERE m.Section = {section}
          AND m.Status = 1
          AND m.ItemType IN (0, 1, 2, 3, 6)
        ORDER BY t.ParentId, t.Position
    """)
    rows = cur.fetchall()

    if not rows:
        return None

    # --- Build all nodes and record parent references ---
    nodes = {}
    parent_map = {}  # obj_id -> parent_id

    for obj_id, name, item_type, date_modified, parent_id, position in rows:
        source = None
        # determine a filepath for this object if it's a "file backed type"
        # (e.g. scene [.docx], note [.rtf], etc as opposed to a folder or root)
        if item_type in Node.get_file_backed_types():
            source = resolve_SmartEdit_document_filepath(
                obj_id, item_type, proj_path, cur
            )

        # convert date modified to Unix Epoch in seconds
        # (standard to use in python's datetime lib)
        epoch_time_seconds = filetime_to_epoch(date_modified)
        nodes[obj_id] = Node(
            name=name,
            id=obj_id,
            type=item_type,
            section=section,
            position=position,
            date_modified=epoch_time_seconds,
            source=source,
        )
        parent_map[obj_id] = parent_id

    # --- Link parents to children and determine section root ---
    section_root = None
    for obj_id, node in nodes.items():
        # root node is only one that's type 0
        if node.type == 0:
            section_root = node
        parent_id = parent_map[obj_id]
        if parent_id in nodes:
            nodes[parent_id].add_child(node, sort_by, sort_reverse)

    if not section_root:
        raise Exception(f"no section root found for {section}")

    return section_root


def get_project_name(cur):
    """
    Return the project name from the SmartEdit Writer database.

    The project name is stored as the UserDefinedName of the Section 1
    root node (ItemType=0). In SmartEdit Writer, the main manuscript
    section (Section 1) represents the project itself — its root name
    is the name the author gave the project (e.g., "Huckleberry Finn").

    Other known sections (5 = Fragments, 6 = Research) have their own
    ItemType=0 roots with fixed names and are not the project name.
    Sections 2, 3, and 4 have not been observed in sample data and
    their purpose is unknown.

    Args:
        cur (sqlite3.Cursor): Cursor for the project database.

    Returns:
        str: The project name, or "Project" if the Section 1 root
            is not found.
    """
    res = cur.execute(
        "SELECT UserDefinedName FROM MetaData WHERE Section = 1 AND ItemType = 0"
    ).fetchone()

    if res is None:
        return "Project"

    return res[0]


def get_name(obj_id, cur):
    """
    Get the user-defined display name of an item in a SmartEdit Writer
    project.

    The display name is the name a user sets in SmartEdit Writer's UI for
    an item (e.g. for a scene, "Scene by the river - revised". This can
    be renamed in the UI by the user, and will be updated in the db on save)

    The name is stored in the MetaData table's UserDefinedName column
    and reflects whatever the author has typed in the SmartEdit Writer
    UI. This is distinct from the on-disk filename, which is based on
    the item's numeric ID and file extension. The mapping between these
    two identities — UI name and filesystem path — is the core purpose
    of this tool.

    Args:
        obj_id (int): ID of the item in the MetaData table.
        cur (sqlite3.Cursor): SQLite cursor for the project database.

    Returns:
        str: The UserDefinedName value for the item.

    Raises:
        Exception: If no row is found for the given ID, or if the
            query returns multiple rows (should not happen — ID is
            the primary key).
    """
    res = list(
        cur.execute("SELECT UserDefinedName FROM Metadata " + "WHERE ID=" + str(obj_id))
    )
    if not res:
        raise Exception(f"can't determine user defined name for id {obj_id}")
    if len(res) > 1:
        raise Exception(f"query in sqlite db returned more than one name for {obj_id}")
    return res[0][0]


def get_type(obj_id, cur):
    """
    Get the ItemType of an item in a SmartEdit Writer project.

    ItemType is the discriminator column in the MetaData table that
    determines what an item *is*: folder (1), scene (2), note (3),
    bookmark (5), file/image (6), or root node (0). The type governs
    whether the item has a corresponding file on disk, which extension
    table holds its type-specific data (Documents, Files, Bookmarks),
    and which icon it receives in the report output.

    For the authoritative mapping of ItemType values, see:
        docs/smartedit-schema-reference.md

    Args:
        obj_id (int): ID of the item in the MetaData table.
        cur (sqlite3.Cursor): SQLite cursor for the project database.

    Returns:
        int: The ItemType value for the item.

    Raises:
        Exception: If no row is found for the given ID, or if the
            query returns multiple rows.
    """
    res = list(
        cur.execute("SELECT ItemType FROM Metadata " + "WHERE ID=" + str(obj_id))
    )
    if not res:
        raise Exception(f"can't determine type for id {obj_id}")
    if len(res) > 1:
        raise Exception(f"query in sqlite db returned more than one type for {obj_id}")
    return res[0][0]


def get_parent_id(obj_id, cur):
    """
    Get the ID of the parent of an item in the project tree.

    SmartEdit Writer stores the manuscript hierarchy in the
    DisplayTrees table, where each row maps an item (ItemId) to its
    parent (ParentId). A ParentId of 0 indicates a root-level item
    — one of the top-level section nodes (Manuscript, Fragments)
    that sit directly under the project.

    This function is used by project_tree() during its recursive walk
    from a leaf item up to the root, building the ancestry chain
    that determines the item's position in the report's tree view.

    Note: Research items (Section 6) use the ResearchTree table
    instead. This function currently queries only DisplayTrees.

    Args:
        obj_id (int): ID of the item in the MetaData table.
        cur (sqlite3.Cursor): SQLite cursor for the project database.

    Returns:
        int or None: The ParentId of the item, or None if the item
            has no parent (i.e., it is a root node or not present
            in DisplayTrees).
    """
    res = list(
        cur.execute(
            "SELECT ParentId FROM DisplayTrees " + "WHERE ItemId=" + str(obj_id)
        )
    )
    if not res:
        # no parent -- root level
        return None
    if len(res) > 1:
        raise Exception(f"found more than one parent for scene {obj_id}!")
    return res[0][0]


def get_files_extension(item_id, cur):
    """
    Get the file extension for an ItemType 6 item from the Files table
    in the SmartEdit Writer project sqlite database.

    ItemType 6 covers user-attached binary files (images, PDFs, etc.).
    Unlike scenes (.docx) and notes (.rtf), the extension is not
    hardcoded — it is stored in the Files table at the time the user
    attaches the file to the project.

    Callers should only invoke this for ItemType 6 items. The function
    queries by MetaData.ID and does not validate the item type.

    Args:
        item_id (int): MetaData.ID of the item.
        cur (sqlite3.Cursor): Cursor for the project database.

    Returns:
        str or None: The file extension without the leading dot
            (e.g., "jpg"), or None if no Files row exists for this
            item ID.
    """
    res = cur.execute(
        "SELECT Extension FROM Files WHERE ItemId = ?", (item_id,)
    ).fetchone()

    if res is None:
        return None

    # Extension col in Files table includes . (".png")
    # strip it to match _TYPE_REGISTRY format
    return res[0].lstrip(".")


def resolve_SmartEdit_document_filepath(obj_id, obj_type, project_path, cur):
    """
    Determine the path to a source file in a SmartEdit Writer project.

    The filepaths for files in projects are *not* stored in the
    Sqlite database. Rather, the filepath is pieced together from
    the following facts:
    - SmartEdit Writer stores all files in dedicated directories:
      Documents/ for .docx (scenes), .rtf (notes),
      Files/ for image files
    - File basename is based on MetaData.ID of the item
    - MetaData.ItemType correlates to a file type (ItemType 2 = .docx,
      ItemType 3 = .rtf)
    So for example, an object in MetaData table with FileType=2,
    ID=51 correlates to file Documents/51.docx (nested in the user's
    directory for that project)

    Args:
        obj_id (int): MetaData.ID of the item (used as the filename stem).
        obj_type (int): MetaData.ItemType of the item.
        project_path (Path): path to the SmartEdit write project.
        cur (sqlite3.Cursor): Cursor for the project database.

    Returns:
        Path: Absolute path to the source file.

    Raises:
        Exception: If obj_type is not a supported file-backed type.
    """

    # ensure the type associated with this object is currently supported
    if not Node.is_file_backed_type(obj_type):
        valid_types = ", ".join(str(t) for t in sorted(Node.get_file_backed_types()))
        raise Exception(
            f"Object type {obj_type} is not currently supported for display. Can't determine filename. Valid types: {valid_types}"
        )

    # special case: ItemType 6 is a file in Files/ dir (which can be
    # .png, .jpg, .pdf -- any general file type).
    # It requires dynamic lookup so not stored the Node class registry.
    if obj_type == 6:
        ext = get_files_extension(obj_id, cur)
    else:
        # get extension for an object of this type
        ext = Node.get_extension(obj_type)
        if not ext:
            raise Exception(
                f"Can't determine extension for ItemType={obj_type}. Should not happen as is_file_backed_type returned True. Investigate."
            )

    # get relevant directory within the project that docs of this type are stored in
    file_directory = Node.get_directory(obj_type)
    if not file_directory:
        raise Exception(
            f"Can't determine directory within project for ItemType={obj_type}. Should not happen as is_file_backed_type returned True. Investigate."
        )

    return project_path / file_directory / f"{obj_id}.{ext}"


# ============================================================================
# JSON PRINTING
# ============================================================================


def print_projects_json(projects, short, indent, console, output=None, force=False):
    """Print scene mappings for multiple projects to stdout in JSON format.

    Args:
        projects (list[dict]): A list of project data dicts, each with keys:
            - "name" (str): The project directory name.
            - "tree" (Node): Root Node of the project's manuscript tree.
            as returned by get_projects_data()
        short (bool): only display filenames of the src files in JSON
            rather than entire abs paths
        indent (int): Number of spaces for JSON indentation.
        console (bool); If True, prints JSON to stdout.
        output (Path or None): If Path, write JSON to this path.
        force (bool): overwrite output if exists

    Returns:
        None
    """

    if not console and not output:
        print(
            f"\n{BOLD}{MAGENTA}Warning{RESET}: print_project_json called without "
            f"output or console. JSON will not be printed to stdout or file. "
            f"Investigate as this should not happen",
            flush=True,
        )

    # For each project, get its root tree
    # and call its to_dict() method to serialize.
    projects_json = [p["tree"].to_dict(short) for p in projects]

    if console:
        print(json.dumps(projects_json, indent=indent, ensure_ascii=False), flush=True)

    # write output second so user messages won't get buried beneath console output
    if output:
        if output.exists() and not force:
            print(
                f"{RED}Output already exists: {output}. {BOLD}(Try re-running script with --force){RESET}",
                file=sys.stderr,
                flush=True,
            )
            sys.exit(1)

        output.parent.mkdir(parents=True, exist_ok=True)
        with open(output, "w", encoding="utf-8") as f:
            json.dump(projects_json, f, indent=indent)
            # add trailing newline to prevent issues with cat, wc -l, etc
            # (json.dump doesn't add trailing newline even with indent)
            f.write("\n")
        print(f"\n{BOLD}{BLUE}JSON written to: {GREEN}{output}{RESET}")


# ============================================================================
# STDOUT PRINTING
# ============================================================================


PROJ_SEP = "─"
TITLE_SEP = ". "
SEP_LENGTH = 50


def _print_separator(separator):
    """Print a horizontal separator line using the given character."""
    # how many separators to print based on sep length
    num_seps = int(SEP_LENGTH / len(separator))
    print(separator * num_seps)


def _line_separator():
    """Print a separator line using the TITLE_SEP character."""
    _print_separator(TITLE_SEP)


def _proj_separator():
    """Print a separator line using the PROJ_SEP character."""
    _print_separator(PROJ_SEP)


def print_projects(projects, short):
    """Print scene mappings for multiple projects to stdout."""

    print()
    for i, project in enumerate(projects):
        if not "name" in project or not "tree" in project:
            raise Exception(
                "print_projects: 'name' or 'tree' attributes missing from project"
            )
        _proj_separator()
        print_project(project["tree"], project["name"], short)
    _proj_separator()
    print()


def print_project(curr_tree, proj_name, short):
    """Print the scene mapping for a project to stdout"""

    print(f"📚 {proj_name}")
    _line_separator()

    print_project_tree(curr_tree, short)


# ============================================================================
# STDOUT TREE DISPLAY HELPERS
# ============================================================================


def _max_icon_width():
    """Return the width of the widest icon in both registries."""
    max_w = 0
    for props in Node._TYPE_REGISTRY.values():
        if props.get("icon"):
            max_w = max(max_w, display_width(props["icon"]))
    for props in Node._SECTION_REGISTRY.values():
        if props.get("icon"):
            max_w = max(max_w, display_width(props["icon"]))
    return max_w


# only calculate once per run
_MAX_ICON_WIDTH = _max_icon_width()


def _max_line_width(node):
    """
    Return the width of the widest line in the tree.

    A "line" is everything printed before the source file arrow:
    the tree connector prefix plus the node display (icon + name).
    For example, given this tree fragment:

        ├─ 📁 First Draft
        │  ├─ 📄 Introduction
        │  └─ 📁 Chapter 1
        │     ├─ 📄 Chapter start
        │     └─ 🗒️ Notes

    Used to align source file paths when printing the tree to stdout.

    Args:
        node (Node): Root node of the tree (or subtree) to measure.

    Returns:
        int: The width in terminal columns of the widest line
            in the tree.
    """
    max_len = _line_width(node)
    for child in node.children:
        max_len = max(max_len, _max_line_width(child))
    return max_len


def _node_display(node):
    """
    string to display in stdout tree printing for a node
    e.g. "🗒️ Todo: Today's work"
    """

    # get true width of this icon/emoji, and pad with
    # whitespace to match the widest icon in the tree
    # so that all siblings align.
    icon = node.icon
    icon_width = display_width(icon)
    padding = " " * (_MAX_ICON_WIDTH - icon_width)
    return f"{icon}{padding} {node.name}"


def _line_width(node):
    """Determine the width of the line for a node in stdout tree"""
    # get stdout node display
    node_display = _node_display(node)
    # account for ancestor connectors
    # (there's 1 connector for each ancestor,
    # and each connector is 3 spaces). examples:
    #    "│  │  ├─ Chapter start"
    #    "│     ├─ Chapter start"
    connector_padding = node.depth * 3
    node_display_width = display_width(node_display)
    return node_display_width + connector_padding


def print_project_tree(node, short, max_tree_line_width=0, prefix=""):
    """
    Print a Node tree to stdout with modern formatting.

    Uses emoji icons and box-drawing characters for tree structure.
    Source file paths are aligned to a consistent column after names.

    Args:
        node (Node): Node object for the current tree position.
        short (bool): If True, display only filenames, not full paths.
        max_tree_line_width (int): Width of the widest line in the tree
            (ancestory connectors + node icon + space + name), used to
            align source file paths. Computed on the root call.
        prefix (str): String prefix for tree connector characters
            (used internally for recursion). Each connector is 3
            characters wide (e.g., "├─ " or "└─ "). The prefix
            accumulates as the tree deepens, e.g.:
              depth 1: "├─ "
              depth 2: "│  ├─ "
              depth 3: "│  │  ├─ "
    """

    # This is the root node (first call):
    # get the max width of all nodes in the tree.
    if node.is_root:
        max_tree_line_width = _max_line_width(node)

    # Build the line (no connector prefix for root)
    # Has three elements:
    # 1. connector prefix (e.g. |  |  |-)
    # 2. display for node (e.g. icon name)
    # 3. (optional) source file (for file nodes)

    node_display = _node_display(node)

    line = f"{prefix}{node_display}"

    # Append source file for document nodes (e.g. scenes, notes), aligned to max_tree_line_width
    if node.source:
        source_path = node.source.name if short else str(node.source)
        padding = " " * (max_tree_line_width - _line_width(node) + 2)
        line += f"{padding}→  {source_path}"

    print(line)

    # Recurse into children and determine each child's own
    # tree-drawing prefix, based on current nodes' prefix
    for i, child in enumerate(node.children):
        # check if last child of current node to determine
        # this chil'd connector: last child gets └─ instead of ├─
        is_last = i == len(node.children) - 1
        connector = "└─ " if is_last else "├─ "

        # get the prefix of connectors for this child
        if node.is_root:
            # Case: current node is root node:
            # it's children have no ancestor prefix to inherit,
            # just the connector we just determined.
            child_prefix = connector
        else:
            # Case: the current node has parents:
            # it's children's connector prefix will inherit from its own prefix
            #
            # How to build:
            # --------------
            # The current node was drawn with a prefix like "│  ├─ ".
            # That prefix is made of:
            #   - ancestor lines from higher levels ("│  ")
            #   - the connector that was drawn for the current node ("├─ ")
            #
            # For a child, we need to:
            #   1. Keep the ancestor lines ("│  ")
            #   2. Replace the current node's connector with either a vertical
            #      bar ("│  ") if this node has more siblings, or spaces
            #      ("   ") if this is the last child
            #   3. Add a new connector for the child ("├─ " or "└─ ")
            #
            # Example 1: parent (current node) has prefix "│  ├─ "
            #   e.g. its line is "│  ├─ Chapter 5"
            # - The ending ├─ connector means current node not a last
            #   child of its parent. Will strip that off.
            # - the "continuation" (what to replace ending with) will be
            #   a | (rather than " "), as the children must account for
            #   the current node's siblings that follow it
            # - Each child for the current node gets:
            #   (ancestor line) (continuation) (connector, basd on if its last child)
            # - Final tree at this point ends up:
            #   (current node)                     "│  ├─ Chapter 5"
            #   (current nodes regular children) → "│  │  ├─ Chapter start"
            #   (current node's last child       → "│  │  └─ Notes"
            #
            # Example 2: parent (current node) has prefix "│  └─ "
            #   e.g. its line is "│  └─ Chapter 5"
            # - The ending └─ connector means it was the last child of its parent
            # - the "continuation" (what to replace it with) will be
            #   a " " (rather than |) (as children do NOT need to accont
            #   for current nodes siblings, as none follow it)
            # - Final tree at this point ends up:
            #          current node:    "│  └─ Chapter 5"
            #          regular children "│     ├─ Chapter start"
            #          last child       "│     └─ Notes"
            ancestor_line = prefix[:-3]
            # If the current node (this child's parent) was a last child,
            # use spaces for continuation; otherwise, draw a vertical bar
            # to indicate more siblings above.
            continuation = "   " if prefix.endswith("└─ ") else "│  "
            child_prefix = ancestor_line + continuation + connector

        print_project_tree(child, short, max_tree_line_width, child_prefix)


# ============================================================================
# HTML TREE GENERATION (BEAUTIFULSOUP)
# ============================================================================


def make_tree(tree, short, icon_tree_root):
    """
    Creates HTML for a nested <ul> tree containing
    the mapping of scenes and their source files.

    Args:
        tree (Node): root tree Node for project generated by db_info()
        short (bool): only display the filename of a source
            file, rather than its entire absolute path
        icon_tree_root (str): CSS class for icon to use for tree root

    Returns:
        BeautifulSoup Tag (a <ul class="tree"> element)
    """
    root_ul = SOUP.new_tag("ul")
    root_ul["class"] = "tree"
    make_tree_recursive(root_ul, tree, short, icon_tree_root, expandable=False)
    return root_ul


def make_tree_recursive(parent_ul, curr_node, short, icon_tree_root, expandable=True):
    """
    Recursively build nested <ul>/<li> elements from a Node tree.

    Each child of the given node is rendered as an <li>. Nodes with
    children of their own become collapsible containers. Leaf nodes
    with a source file get a link to the on-disk document.

    Args:
        parent_ul (Tag): BeautifulSoup Tag — the <ul> to append <li> children to.
        curr_node (Node): Node object representing the current tree position.
        short (bool): If True, display only filenames for source links.
        icon_tree_root (str): CSS class for the root node's icon.
        expandable (bool): Whether nodes at this level should be collapsible.
            Set to False for the root to exclude it from Expand All /
            Collapse All controls.
    """

    # Render current node
    li = build_li(
        node=curr_node,
        short=short,
        expandable=expandable,
        icon_tree_root=icon_tree_root,
    )
    parent_ul.append(li)

    # Render all children (if any) inside current node's <li>
    if curr_node.has_children:
        child_ul = SOUP.new_tag("ul")
        for child in curr_node.children:
            # only root node should be un-expandable
            # this is a child (so not root), so it should be expandable
            make_tree_recursive(child_ul, child, short, icon_tree_root, expandable=True)
        li.append(child_ul)


def build_li(
    node,
    short,
    expandable,
    icon_tree_root,
):
    """
    Build an <li> for a tree node (leaf, folder, scene-with-children, or root).

    Args:
        node (Node): Node in project tree to build the <li> for
        short (bool): show only the filename, not the full path
        expandable (bool): whether the node should be collapsible
        icon_tree_root (str): CSS class for the root icon

    Returns:
        BeautifulSoup Tag (<li>)
    """

    name = node.name
    source = node.source
    is_root = node.is_root

    li = SOUP.new_tag("li")
    li["class"] = _build_node_classes(node, expandable)

    # --- Build the visible row ---
    content_div = SOUP.new_tag("div")
    content_div["class"] = "node-content"

    if is_root:
        # Root node: project-level collapse toggle with ⊞/⊟ icons
        toggle_span = SOUP.new_tag("span")
        toggle_span["class"] = "project-toggle"
        expanded_icon = SOUP.new_tag("span")
        expanded_icon["class"] = "toggle-icon expanded-icon"
        expanded_icon.string = "⊟"
        collapsed_icon = SOUP.new_tag("span")
        collapsed_icon["class"] = "toggle-icon collapsed-icon"
        collapsed_icon.string = "⊞"
        toggle_span.append(expanded_icon)
        toggle_span.append(collapsed_icon)
        content_div.append(toggle_span)

    # Twistie (hidden via CSS for leaf nodes, but keeps alignment;
    # actual arrow controlled via CSS ::before)
    twistie = SOUP.new_tag("span")
    twistie["class"] = "twistie"
    content_div.append(twistie)

    # Icon
    icon_span = SOUP.new_tag("span")
    if is_root:
        icon_span["class"] = ["icon", icon_tree_root]
    else:
        icon_span["class"] = "icon"
    content_div.append(icon_span)

    # Name
    name_span = SOUP.new_tag("span")
    name_span["class"] = "name"
    name_span.string = name
    content_div.append(name_span)

    # Scene count badge (root node only)
    if is_root:
        scene_count = count_leaves(node)
        count_span = SOUP.new_tag("span")
        count_span["class"] = "scene-count"
        count_span.string = f"({scene_count} scenes)"
        content_div.append(count_span)

    # Source link (shown for scenes that have a file, whether
    # or not they also act as containers)
    if source:
        display_path = source.name if short else str(source)
        file_uri = "file:///" + str(source)
        link = SOUP.new_tag("a", href=file_uri)
        link["class"] = "source-link"
        link["target"] = "_blank"
        link.string = display_path
        content_div.append(link)

        # Copy filepath icon
        copy_span = SOUP.new_tag("span")
        copy_span["class"] = "copy-path"
        copy_span["title"] = "Copy full filepath to clipboard"
        copy_span["data-path"] = str(source)
        content_div.append(copy_span)

    li.append(content_div)

    return li


def _build_node_classes(node, expandable=True):
    """
    Build the list of CSS classes for a tree-node <li>.

    Args:
        node (Node): Node in tree to build the CSS class list for.
        expandable (bool): whether the node should be collapsible
            via Expand All / Collapse All and click-to-toggle. Nodes
            with children but expandable=False (e.g. the root) still
            get .has-children but omit .expandable and the twistie.

    Returns:
        list[str]: list of strings of CSS class names
    """
    classes = ["tree-node"]
    css_class = node.css_class
    if css_class:
        classes.append(node.css_class)
    if node.has_children:
        classes.append("has-children")
        if expandable:
            classes.append("expandable")
    if node.is_root:
        classes.append("tree-root")
    if node.is_leaf:
        classes.append("leaf-scene")
    return classes


def count_leaves(node):
    """
    Count the total number of leaves in a Node tree.

    A leaf is any node with no children and a non-None source file.
    These are the terminal items with on-disk documents.

    Args:
        node (Node): Root Node of the tree (or subtree) to count.

    Returns:
        int: Total count of leaf nodes with source files.
    """
    count = 0
    if not node.children and node.source is not None:
        count = 1
    for child in node.children:
        count += count_leaves(child)
    return count


# ============================================================================
# HTML REPORT GENERATION
# ============================================================================


def create_HTML_reports(
    projects,
    template,
    short,
    assets_src,
    converted_css,
    output,
    html_output,
    force,
    force_assets,
    force_html,
    nuclear,
    tree_icons,
    merge,
    browser,
    convert,
    reuse,
):
    """
    Create one or more HTML reports for the given projects.

    If merge is True, all projects are combined into a single report.
    If merge is False, a separate report is generated for each project.

    Delegates to create_HTML_report() for each individual report file.

    Args:
        projects (list[dict]): A list of project data dicts, each with keys:
            - "name" (str): The project directory name.
            - "tree" (Node): Root Node of the project's manuscript tree.
            as returned by get_projects_data()
        template (Path): Path to the HTML template file that provides
            the page skeleton (%TITLE% and %TREES% placeholders).
        short (bool): only display filenames of the src
            files rather than entire abs paths
        assets_src (Path): Path where source assets/ lives.
        converted_css (str): content of CSS for converted files
        output (Path): Directory to write HTML report(s) into.
        html_output (Path): Directory to write converted HTML files to.
            Required only when convert=True.
        force (bool): overwrite output if exists
        force_assets (bool): If True, overwrite an existing assets/
            directory at the destination. If False and the destination
            assets/ already exists, the copy is skipped and existing
            assets are used as-is (preserving any user customizations).
        nuclear (bool): If True, uses aggressive deletion that strips read-only
            permissions before retrying (Windows only). Implies force.
            This is used when force alone fails.
        tree_icons (list[str]): list of CSS classes available to assign to
            root node of project (the classes should have corresponding
            rules in style.css).
        merge (bool): Merge all projects into a single HTML report
            (if False, one report generated for each project)
        browser (bool): Open HTML report(s) in the browser.
        convert (bool): Convert .docx and .rtf source files to HTML for
            inline viewing in the report.
        reuse (bool): If True, skip conversion for source files whose
            converted HTML output already exists on disk. Files that
            have not yet been converted will still be processed.
            Defaults to False.

    Returns:
        None
    """

    # lists of projects to go in each report
    # one list for each project to create
    project_lists = []
    if merge:
        # a single report -- all projects in single report
        project_lists = [projects]
    else:
        # one report for each project
        project_lists = [[project] for project in projects]

    # create one report for each list of projects
    for project_list in project_lists:
        create_HTML_report(
            project_list=project_list,
            template=template,
            short=short,
            assets_src=assets_src,
            converted_css=converted_css,
            output=output,
            html_output=html_output,
            force=force,
            force_assets=force_assets,
            force_html=force_html,
            nuclear=nuclear,
            tree_icons=tree_icons,
            merge=merge,
            browser=browser,
            convert=convert,
            reuse=reuse,
        )


def create_HTML_report(
    project_list,
    template,
    short,
    assets_src,
    converted_css,
    output,
    html_output,
    force,
    force_assets,
    force_html,
    nuclear,
    tree_icons,
    merge,
    browser,
    convert,
    reuse,
):
    """
    Generate a single static HTML report for a list of SmartEdit Writer projects.

    Constructs the report from a template, injects the project tree structure,
    optionally converts source files to HTML and injects view links, copies
    assets (CSS, JS, favicon) to the output location, and optionally opens
    the report in the user's default browser.

    For a single project, this produces a standalone report file. For multiple
    projects with merge=False, call this once per project. For merge=True,
    call once with all projects in the list.

    Args:
        project_list (list[dict]): A list of project data dicts to include
            in the report. Each data dict has keys:
            - "name" (str): The project directory name.
            - "tree" (Node): Root Node of the project's manuscript tree.
            This is a sublist of the full project list, created by
            create_HTML_reports() which partitions projects into
            individual reports (one per project, or all in one if merged).
        template (Path): Path to the HTML template file that provides
            the page skeleton (%TITLE% and %TREES% placeholders).
        short (bool): If True, display only filenames in source links rather
            than full absolute paths.
        assets_src (Path): Path to the source assets directory containing
            CSS, JS, and other static resources.
        converted_css (str): CSS content to inject into converted HTML files
            (from CONVERTED_STYLES dict, or empty string for no style).
        output (Path): Directory to write the HTML report report into.
        html_output (Path): Directory to write converted HTML files to.
            Required only when convert=True.
        force (bool): If True, overwrite an existing report file at output.
        force_assets (bool): If True, overwrite an existing assets/ directory
            at the destination. If False and assets/ already exists, the copy
            is skipped and existing assets are used as-is.
        force_html (bool): If True, overwrite existing converted HTML files.
            Requires convert=True.
        nuclear (bool): If True, use aggressive deletion that strips read-only
            permissions before retrying (Windows only). Implies force.
        tree_icons (list[str]): List of CSS classes to assign to project root
            icons. Classes must have corresponding rules in style.css.
        merge (bool): If True, this report contains multiple projects. Affects
            output path resolution and report title generation.
        browser (bool): If True, open the generated report in the user's
            default browser.
        convert (bool): If True, convert .docx and .rtf source files to HTML
            and inject view links into the report.
        reuse (bool): If True, skip conversion for source files whose
            converted HTML output already exists on disk. Files that
            have not yet been converted will still be processed.
            Defaults to False.

    Returns:
        None
    """
    # create base file from template file
    soup = beautiful_soup_utils.make_soup_from_file(template, False)
    # generate BeautifulSoup for the file for list of projects
    project_soup = generate_report_content(project_list, short, tree_icons)
    # get title for <title> tag
    page_title = get_report_title(project_list)
    # get a "name" for this report
    report_name = get_report_name(project_list)
    beautiful_soup_utils.find_replace_str(soup, "%TREES%", project_soup)
    beautiful_soup_utils.find_replace_str(soup, "%TITLE%", page_title)

    # Get output path for static HTML report
    output = output / get_report_filename(merge, project_list)

    # convert source files in the SmartEdit project to HTML and inject view links
    if convert:
        # Specify dir specific to this report to hold converted files
        report_dir = html_output / safe_name(f"report-{report_name}")
        inject_view_links(soup, report_dir, converted_css, output, reuse, force_html)

    # If output file already exists and force not given, error
    if output.exists() and not force:
        print(
            f"{RED}Output already exists: {output}. {BOLD}(Try re-running script with --force){RESET}",
            file=sys.stderr,
        )
        sys.exit(1)

    beautiful_soup_utils.write_soup_to_file(
        soup,
        str(output),
        force=force,
        preserve_ru=True,
        preserve_html_entities=True,
        fix_yelochki=True,
        taglist=[],
        log=False,
    )

    print(f"\n{BOLD}{BLUE}HTML report written to: {GREEN}{output}{RESET}")

    # copy assets directory to final output
    assets_dest = output.parent / "assets"
    copy_assets_to_output(assets_src, assets_dest, force_assets, nuclear)

    if browser:
        webbrowser.open(str(output))


def get_report_name(project_list):
    """
    Returns a name for a report
    """
    if not project_list:
        raise Exception("get_report_name: No projects in project_list!")

    if len(project_list) == 1:
        # only one project, get its name
        if not "name" in project_list[0]:
            raise Exception("get_report_name: no name attribute on project!")
        return project_list[0]["name"]

    return "merged-project"


def get_report_title(project_list):
    """
    Returns the <title> tag for a report
    """
    if not project_list:
        raise Exception("get_report_title: No projects in project_list!")

    base_title = "SmartEdit Report"
    if len(project_list) > 1:
        return f"{base_title} (Merged Report)"

    # only one project, get its name
    if not "name" in project_list[0]:
        raise Exception("get_report_title: no name attribute on project!")
    project_name = project_list[0]["name"]

    return f"{base_title}: {project_name}"


def get_report_filename(merge, project_list):
    """
    Get a filename for a static HTML report based
    on user selected arguments.
    """

    if merge:
        # merge case: multiple projects in single report
        # so use a generic name.
        return DEFAULT_HTML_REPORT_FILENAME
    else:
        # not merge case: only be one project in the report.
        # use project name for filename
        if len(project_list) > 1:
            raise Exception(
                f"get_report_filename: More than one project in list even though merge not supplied. ({len(project_list)})"
            )

        # get name of the project
        if not "name" in project_list[0]:
            raise Exception("get_report_filename: no name attribute on project!")
        project_name = project_list[0]["name"]

        return f"{project_name}.html"


def generate_report_content(projects, short, tree_icons):
    """
    Generate the BeautifulSoup for a set of projects
    (what should be inserted at %TREES%)
    """
    # shuffle the tree root icons
    temp_icon_list = tree_icons.copy()
    random.shuffle(temp_icon_list)

    content_div = SOUP.new_tag("div")
    # don't change wrapper name - style.css relying on
    # this for card styling for individual projects
    content_div["class"] = "projects-wrapper"
    for i, project in enumerate(projects):
        if not "name" in project or not "tree" in project:
            raise Exception(
                "generate_report_content: 'name' or 'tree' attributes missing from project"
            )
        tree = project["tree"]

        # select a random icon for the tree root
        # (% to loop back around if more projects than icons)
        tree_root_icon = temp_icon_list[i % len(temp_icon_list)]

        tree_soup = make_tree(tree, short, tree_root_icon)
        content_div.append(tree_soup)

    return content_div


# ============================================================================
# COPYING ASSETS TO FINAL HTML REPORT DIR
# ============================================================================


def copy_assets_to_output(
    assets_src: Path, assets_dest: Path, force: bool = False, nuclear: bool = False
) -> None:
    """
    Copy assets directory to another directory.

    This should be called to copy the assets directory in script dir to the
    directory where the final static HTML report will be written (so that
    relative asset references (e.g., `assets/css/styles.css`) resolve correctly
    when the output file is opened in a browser.

    Args:
        assets_src (Path): Path to the source assets directory
        assets_dest (Path): Path to copy assets to.
        force (bool): If True, overwrite existing assets directory; if False, raise
            error if destination already exists.
        nuclear (bool): If True, uses aggressive deletion that strips read-only
            permissions before retrying (Windows only). Implies force.
            This is used when force alone fails.

    Returns:
        None

    Examples:
        >>> from pathlib import Path
        >>> assets = Path("/project/assets")
        >>> output = Path("/project/output/assets")
        >>> copy_assets_to_output(assets, output, force=True)
        # Copies /project/assets to /project/output/assets

    Notes:
        - Uses shutil.copytree for recursive directory copy.
        - The destination directory name matches the source directory name.
        - Existing symlinks are preserved (follow_symlinks=False).
        - If force=True, any existing destination is removed before copying.
    """
    # Validate source
    if not assets_src.exists():
        raise FileNotFoundError(f"Assets src path does not exist: {assets_src}")

    if not assets_src.is_dir():
        raise NotADirectoryError(f"Assets src path is not a directory: {assets_src}")

    # Return if src and dest assets dir are the same
    if same_path(assets_src, assets_dest):
        return

    # Handle existing destination
    if assets_dest.exists():
        if force:
            try:
                remove_path(assets_dest, force, nuclear)
            except Exception as e:
                raise RuntimeError(f"Failed to remove existing assets dir: {e}")
        else:
            print(
                f"\nNote about your report:\n"
                f"- The HTML report needs supporting files (styles, icons, scripts) from an assets/ folder to display correctly.\n"
                f"- This dir is normally copied into the report's output dir from this tool's source:\n"
                f"   {assets_src}\n"
                f"- However, an existing assets/ directory was found in the report's output dir:\n"
                f"   {assets_dest}\n"
                f"- The existing assets/ will be kept as-is (rather than overwriting).\n"
                f"- To replace it with the latest default (overwriting any customizations in the current report assets/), re-run with --force-assets."
            )
            return

    # Copy the directory
    try:
        shutil.copytree(
            assets_src,
            assets_dest,
            symlinks=False,  # Copy symlinks as links (not dereferenced)
            ignore_dangling_symlinks=True,
            dirs_exist_ok=False,  # Should not happen due to check above
        )
    except OSError as e:
        raise OSError(f"Failed to copy assets from {assets_src} to {assets_dest}: {e}")


# ============================================================================
# FILE CONVERSION
# ============================================================================


def inject_view_links(soup, output_dir, converted_css, report_path, reuse, force):
    """
    Find all source links in the BeautifulSoup tree, convert the
    referenced .docx and .rtf files to HTML, and insert view-link
    spans alongside them.

    The converted HTML files are written to output_dir. The view
    links use relative paths computed from report_path so they
    resolve correctly when the report is opened in a browser.

    Args:
        soup: BeautifulSoup object for the HTML report.
        output_dir (Path): Directory to write converted HTML files to.
        converted_css (str): Content of CSS for converted files.
        report_path (Path): Path where the HTML report will be written
            (used to compute relative links to converted files).
        reuse (bool): If True, skip conversion for source files whose
            converted HTML output already exists on disk. Files that
            have not yet been converted will still be processed.
            Defaults to False.
        force (bool): If True, overwrite existing converted HTML files.
    """

    project_dirs = {}
    for link in soup.find_all("a", class_="source-link"):
        href = link.get("href", "")
        # href is "file:///C:/.../123.docx"
        source_path = Path(href.replace("file:///", ""))

        if source_path.suffix.lower() not in (".docx", ".rtf"):
            continue

        # Find which project this link belongs to
        tree_root = link.find_parent("li", class_="tree-root")
        if tree_root:
            project_name = tree_root.find("span", class_="name").string
        else:
            project_name = "unknown"

        # Scope converted files by project to avoid collisions.
        # SmartEdit Writer uses numeric filenames (1.docx, 2.docx)
        # which repeat across projects, so a merged report needs
        # per-project subdirectories.

        # check if dirpath for this project already generated,
        # if so use that. Else, if dirpath ends up having random chars,
        # (happens in cornercase where project name has all special chars)
        # then files for the same project could be split among
        # different dirs (each time file for this project is encountered
        # in the loop, it will get new random chars and thus a new dir)
        if project_name not in project_dirs:
            project_dirs[project_name] = output_dir / safe_name(project_name)
        project_output_dir = project_dirs[project_name]

        html_path = project_output_dir / f"{source_path.stem}.html"
        # If --reuse is set and the converted file already exists,
        # skip the expensive conversion step. This dramatically
        # speeds up repeated report generation for large projects.
        #
        # --force-html is intentionally ignored when --reuse is
        # active. The two flags are contradictory, but --force-html
        # is muscle memory to ensure builds succed and requiring it to be
        # omitted would just be friction. It's harmless here since
        # the file isn't being rebuilt anyway.
        if reuse and html_path.exists():
            # Skip conversion, use existing file. Still need to inject
            # the view link so the report references it.
            pass
        else:
            convert_source_to_html(source_path, html_path, converted_css, force)

        # get rel path from HTML report to HTML file written
        rel_path = os.path.relpath(html_path, report_path.parent)

        view_link = SOUP.new_tag("a", href=rel_path)
        view_link["class"] = "view-html"
        view_link["target"] = "_blank"
        view_link["title"] = "View source content as HTML"
        link.insert_after(view_link)


def write_html_file(
    content: str, output: Path, converted_css: str, force: bool
) -> Path:
    """
    Write the final HTML file, checking for existing file and force parameter.

    Args:
        content (str): Final HTML string.
        output (Path): Path to write html file to
        converted_css (str): string content of CSS for converted files
        force (bool): Whether to overwrite existing file.

    Returns:
        Path: Path to file written

    Raises:
        FileExistsError: If file exists and force is False.
    """
    if output.exists() and not force:
        print(
            f"{RED}HTML file {output} already exists. {BOLD}Use --force-html to overwrite.{RESET}",
            file=sys.stderr,
        )
        sys.exit(1)

    output.parent.mkdir(parents=True, exist_ok=True)

    # convert to BeautifulSoup and prettify
    soup = BeautifulSoup(content, "html.parser")

    # ensure complete HTML document (Mammoth only creates basic <p> content)
    beautiful_soup_utils.ensure_html_document(soup)

    # if css supplied, inject into head
    if converted_css:
        style_tag = soup.new_tag("style")
        style_tag.string = converted_css
        soup.head.append(style_tag)

    # write to disk with custom formatter
    beautiful_soup_utils.write_soup_to_file(
        soup,
        output,
        force=True,
        preserve_ru=True,
        preserve_html_entities=True,
        fix_yelochki=True,
        taglist=[],
        log=False,
    )

    return output


def convert_source_to_html(source_path, output_path, converted_css, force):
    """
    Convert a .docx or .rtf source file to HTML and save it to output_dir.

    Args:
        source_path (Path): path to the .docx or .rtf file
        output_path (Path): path to write the converted HTML file to
        converted_css (str): content of CSS for converted files
        force (bool): if True, overwrite an existing HTML file at the
            destination

    Returns:
        Path: absolute path to the written HTML file
    """
    print(f"\rConverting {source_path.name}...", end="", flush=True)
    suffix = source_path.suffix.lower()
    if suffix == ".docx":
        html = convert_docx_to_html(source_path)
    elif suffix == ".rtf":
        html = convert_rtf_to_html(source_path, indent=0)
    else:
        raise Exception(f"Unsupported format for conversion: {suffix}")
    print(f"\rConverting {source_path.name}... done.", end="", flush=True)
    output_path = write_html_file(html, output_path, converted_css, force)
    print(
        f"\rConverting {source_path.name}... done. Written to {output_path}", flush=True
    )
    return output_path


def convert_docx_to_html(filepath: Path) -> str:
    """
    Convert a .docx file to HTML, preserving headings, lists, bold/italic,
    tables, and basic structure.

    Args:
        filepath (Path): Path to .docx file

    Returns:
        str: HTML string
    """
    import mammoth

    if not filepath.exists():
        raise Exception(f".docx file {filepath} does not exist!")
    if not filepath.suffix.lower() == ".docx":
        raise Exception(f"File is not .docx! {filepath}")

    result = mammoth.convert_to_html(filepath)
    # Log any warnings (e.g., unrecognized styles)
    for message in result.messages:
        print(f"⚠️  Warning: [mammoth] {message}")
    return result.value


def convert_rtf_to_html(filepath: Path, indent: int) -> str:
    """
    Convert Microsoft .rtf file to HTML. Experimental -- use at own risk.

    Limitations:
    - formatting (bold, italic, etc.) NOT preserved
    - certain complex writeups will fail (e.g. write plaintext in Word ->
      save as rtf -> likely fails)
    - certain chars do not render (emdash, etc.)

    Args:
        filepath (Path): Path to .rtf file
        indent (int): Indents new lines in .txt, .rtf by this many spaces
            in final rendered HTML (overrides existing leading spaces to
            make document indentation uniform).

    Returns:
        str: HTML string
    """
    from striprtf.striprtf import rtf_to_text

    if not filepath.exists():
        raise Exception(f".rtf file {filepath} does not exist!")
    if not filepath.suffix.lower() == ".rtf":
        raise Exception(f"File is not .rtf! {filepath}")

    with open(filepath, "rb") as f:
        rtf_bytes = f.read()

    # Decode as ascii, ignoring errors (RTF is 7-bit)
    rtf_bytes = rtf_bytes.decode("ascii", errors="ignore")
    text_string = rtf_to_text(rtf_bytes)

    return convert_raw_text_to_html(text_string, indent)


def convert_raw_text_to_html(raw_text: str, indent: int = 0) -> str:
    """
    Convert raw text string to HTML with paragraph preservation and exact leading whitespace.

    Behavior:
        - Splits text into paragraphs on double newlines (blank lines).
        - Each paragraph is wrapped in <p> tags.
        - Single newlines within a paragraph become <br> tags.
        - Leading spaces/tabs on lines are preserved visually
          by converting each space to &nbsp; and each tab to 4 &nbsp;.
        - If the first line has no leading whitespace, no &nbsp; prefix is added.
        - cyrillic style << >>, « » converted to <em> </em> tags

    Args:
        raw_text (str): string to convert to HTML
        indent (int): int to control indentation of new lines in raw text.
            If > 0, all lines will be indented that many spaces.
            NOTE: Overrides any leading spaces currently present.

    Returns:
         str: HTML string with paragraphs, line breaks, and preserved leading indentation.
    """

    # replacements to make on the raw text
    replacements = []

    # Normalize Windows line endings to Unix-style
    replacements.append(["\r\n", "\n"])

    # convert << >>, « » to <em> </em>
    replacements.extend(
        [["<<", "<em>"], [">>", "</em>"], ["«", "<em>"], ["»", "</em>"]]
    )

    raw_text = sequential_replacements(raw_text, replacements)

    # lines with only * or - (e.g. ***, --) convert to <hr>
    # Notes:
    # 1. must be surrounded by \n to avoid catching valid inline chars e.g. "Then - he paused"
    # 2. pad <hr> with \n\n so surrounding text will be interpreted as paragraphs on next split
    raw_text = re.sub(r"(?<=\n)[*-]+(?=\n)", r"\n\n<hr>\n\n", raw_text)

    # convert following to emdash:
    # 1. - (with space around)
    # 2. -- (with space around)
    # Note: ensure whitespace around on 1., else will convert compound words e.g. "push-ups"

    # {1,2} matches one or two - chars
    raw_text = re.sub(r"(\s)-{1,2}(\s)", r"\1—\2", raw_text)

    # convert ... to … char
    raw_text = raw_text.replace("...", "…")

    # Split on double newlines (blank lines) to identify paragraphs
    paragraphs = re.split(r"\n\s*\n", raw_text)

    html_parts = []
    for para in paragraphs:
        para = para.strip("\n")
        if not para.strip():  # Skip empty paragraphs
            continue

        # User-added <hr>: add and continue to avoid empty line on --indent option
        # (will preprend &nsbp; to "<hr>" which causes blank &nsbp; line above <hr>)
        # note: only check startswith "<hr" (not == "<hr>") in case css classes, etc.
        if para.strip().startswith("<hr"):
            html_parts.append(para)
            continue

        lines = para.split("\n")
        if not lines:
            continue

        # preserve leading whitespace in lines
        for i, line in enumerate(lines):
            preserve_prefix = ""
            num_spaces = 0
            if indent:
                # add uniform num of spaces to all lines,
                # regardless of how many currently present.
                num_spaces = indent
            else:
                # Convert leading spaces/tabs to &nbsp; entities
                for ch in line:
                    if ch == " ":
                        num_spaces += 1
                    elif ch == "\t":
                        num_spaces += 4
                    else:
                        break  # Stop at first non-whitespace character
            preserve_prefix += "&nbsp;" * num_spaces
            lines[i] = f"{preserve_prefix}{line}"

        # Rebuild paragraph with <br> for newlines
        para_with_br = "<br>\n".join(lines)
        html_parts.append(f"<p>{para_with_br}</p>")

    return "\n".join(html_parts)


def sequential_replacements(text: str, replacements: list[list[str, str]]) -> str:
    """Apply a series of substring replacements

    Each replacement replaces all occurrences of a substring before the next
    replacement is applied. This means later replacements will operate on the
    output of earlier ones, which can produce unexpected results when
    replacements are not independent (e.g., swapping values or overlapping
    patterns).

    Args:
        text (str): The input string to modify.
        replacements (list[list[str,str]]): A list of [target, replacement] pairs.
            Each pair must contain exactly two strings.

    Returns:
        str: The transformed string after applying all replacements in order.

    Example:
        >>> sequential_replacements("ab", [["a", "b"], ["b", "a"]])
        "aa"  # Note: not "ba" due to sequential application.
    """
    for target, replacement in replacements:
        text = text.replace(target, replacement)
    return text


# ============================================================================
# ARGPARSE WRAPPER/HELPER FUNCTIONS
# ============================================================================
#
# These functions wrap argparse's internal API (parser._actions) to
# provide cleaner access to argument definitions and provenance
# tracking. Understanding two argparse concepts is essential:
#
# DEST:
#   When you define a flag like --html-output, argparse stores the
#   parsed value in a Namespace under a "dest" attribute. The dest
#   is derived from the long flag name: strip the leading "--" and
#   convert hyphens to underscores. --html-output → html_output.
#   Short and long flags with the same meaning share a dest:
#   -p and --project both map to "project".
#
# ACTION:
#   Internally, argparse stores each argument definition as an
#   "action" object in parser._actions. Each action holds the
#   flag strings (option_strings), the dest, the default value,
#   the type, and other metadata about that argument.
#
#   These helper functions attach additional metadata to actions
#   (e.g., whether a config file value was applied, and what the
#   original default was before config). This enables provenance
#   tracking: given a flag, you can determine whether its value
#   came from the CLI, a config file, or the built-in default.
#
# _ACTIONS STABILITY:
#   parser._actions is technically a private API. It has been stable
#   for 15+ years and is widely used in the community, but it is
#   not officially documented. These helpers isolate the reliance
#   on _actions so that if it ever changes, only this section
#   needs updating.
# ============================================================================


def get_dests(parser):
    """
    Get list of all .dest attrs for user-defined arguments in an
    argparse parser
    """
    return [a.dest for a in parser._actions if a.dest and a.dest != "help"]


def get_arguments(parser):
    """
    Get list of all arguments (e.g. ["--project", "-p", "--output"])
    defined in an argparse parser
    """
    valid_arguments = set()
    for action in parser._actions:
        # get list of CLI args that map to
        # this action (e.g. ['--project', '-p'])
        action_arguments = action.option_strings
        valid_arguments.update(action_arguments)
    return list(valid_arguments)


def get_dest(parser, argument, fail_if_missing=True):
    """
    Given an argument string (e.g. "--html-output") get corresponding
    dest string in parser
    """
    for action in parser._actions:
        # get list of CLI args that map to
        # this action (e.g. ['--project', '-p'])
        action_arguments = action.option_strings
        if argument in action_arguments:
            return action.dest

    if fail_if_missing:
        valid_arguments = get_arguments(parser)
        raise ValueError(
            f"Not a valid argument: '{argument}'. Valid args: {', '.join(valid_arguments)}"
        )


def get_action(parser, dest, fail_if_missing=True):
    """Given a dest string in a parser, get its action object"""
    for action in parser._actions:
        if action.dest == dest:
            return action

    if fail_if_missing:
        valid_dests = get_dests(parser)
        raise ValueError(
            f"Not a valid dest: '{dest}'. Valid dests: {', '.join(valid_dests)}"
        )


def get_argument_list(parser, argument, fail_if_missing=True):
    """
    Get all CLI flag forms that map to the same argparse argument

    Args:
        parser (argparse.ArgumentParser): The parser object containing
            the argument definitions.
        argument (str): argument to check. Should be what's added
            in parser.add_argument (e.g. "-p" or "--project")
        fail_if_missing (bool): If True, raise ValueError if the
            argument doesn't exist in the paser. Defaults to True.

    Example:
        >>>    parser = argparse.ArgumentParser()
        >>>    parser.add_argument("-p", "--project")
        >>>    get_argument_list(parser, "--project")
        >>>    # returns ["-p", "--project"]
    """
    for action in parser._actions:
        # get list of CLI args that map to
        # this action (e.g. ['--project', '-p'])
        action_arguments = action.option_strings
        if argument in action_arguments:
            return action_arguments

    if fail_if_missing:
        valid_arguments = get_arguments(parser)
        raise ValueError(
            f"Not a valid argument: '{argument}'. Valid args: {', '.join(valid_arguments)}"
        )

    return []


def user_supplied(parser, argument, check_all=True, fail_if_missing=True):
    """
    Checks if a user supplied an ArgParse defined parameter on CLI

    Args:
        parser (argparse.ArgumentParser): The parser object containing
            the argument definitions.
        argument (str): argument to check. Should be what's added
            in parser.add_argument (e.g. "-p" or "--project")
        check_all (bool): If True, checks if any mapped arguments for
            this argument were supplied. (e.g. if "-p" and "--project"
            both map to the same argparse Namespace destination, and
            user supplied "--project" on the command line, then both
            user_supplied(parser, "-p") and user_supplied(parser, "--p")
            would return True; else only user_supplied(parser, "--p")
            would return True)
        fail_if_missing (bool): If True, raise ValueError if the
            argument doesn't exist in the paser. Defaults to True.
            Set to False when callers want to probe for existence
            without raising.

    Example:
        >>>    parser = argparse.ArgumentParser()
        >>>    parser.add_argument("-p", "--project")
        >>>    user_supplied(parser, "--project")

    Returns:
        bool: True if the user supplied this argument on the command line.
            False otherwise.

    Raises:
        ValueError: If fail_if_missing is True and argument not defined in parser
    """

    # get all arguments that correlate with this one

    # important: get_argument_list is the function which actually
    # validates if the arg is valid, so call it regardless of check_all
    all_args = get_argument_list(parser, argument, fail_if_missing)
    args_to_check = all_args if check_all else [argument]

    # loop through sys.argv (user supplied args) + valid options
    # for this param and check:
    # 1. is there any exact match (e.g. one of the valid options
    #    matched a user supplied arg)
    # 2. if one of the user supplied args starts with
    #    option=  (e.g. --style="mystyle")
    for arg in sys.argv:
        for arg_to_check in args_to_check:
            if arg == arg_to_check or arg.startswith(arg_to_check + "="):
                return True
    return False


def config_supplied(parser, argument, fail_if_missing=True):
    """
    Check if an argument was applied to the argparse
    parser via a config file
    """
    # get dest value in argparse namespace for this argument
    dest = get_dest(parser, argument, fail_if_missing)
    # get action for this dest
    action = get_action(parser, dest, fail_if_missing)
    # attr .config set on this action in apply_config
    return getattr(action, "config", False)


def any_supplied(parser, argument, check_all=True, fail_if_missing=True):
    """Return boolean indicating if any arg was supplied on CLI or config file"""
    user_supplied_arg = user_supplied(parser, argument, check_all, fail_if_missing)
    config_supplied_arg = config_supplied(parser, argument, fail_if_missing)
    return user_supplied_arg or config_supplied_arg


def get_original_default(parser, argument, fail_if_missing=True):
    """
    Get original .default for an argument definition in the parser
    Concept: apply_config, which applies the toml config file,
    overwrites the defaults supplied in add_argument statements;
    it saves each action's original default in a default_original
    attribute for future reference
    """
    # get dest value in argparse namespace for this argument
    dest = get_dest(parser, argument, fail_if_missing)
    # get action for this dest
    action = get_action(parser, dest, fail_if_missing)
    # attr .default_original set on this action in apply_config
    return getattr(action, "default_original", None)


def apply_config(parser, config):
    """
    Apply config file values as argparse defaults.

    Takes a dict loaded from a TOML config file (e.g., via tomllib
    or tomli) and updates the argparse parser's argument defaults.

    Config keys must match argparse dest names (long flag with
    leading -- stripped and hyphens converted to underscores).

    Args:
        parser (argparse.ArgumentParser): The parser whose defaults
            should be updated. All arguments should be defined
            before calling this function.
        config (dict): Mapping of argparse dest names to config
            values. Values must be the correct Python types for
            the corresponding parser actions (e.g., bool for
            store_true, Path for type=Path).

    Example:
        argparse parser defined with args:

            parser.add_argument(
                "--style",
                choices=["default", "novel"],
                default="default",
            )
             parser.add_argument(
                "--sort",
                type=str,
                choices=["position", "name", "date_modified"],
                default="position",
            )


        TOML config file contents:

            style = "novel"
            sort = "date_modified"

        Code:

            config = tomllib.load(f)
            apply_config(parser, config)
            args = parser.parse_args()

        If user runs with no flags, args.style is "novel" and
        args.sort is "date_modified". If user runs with
        --style minimal, args.style is "minimal" and args.sort
        is still "date_modified".
    """

    # config file keys are 'dest' names (e.g. long flag with no --
    # and - converted to _
    #
    # For each key / value in the config file:
    # 1. find its corresponding action object in the argparse
    #    parser (holds the metadata for that argument -- default,
    #    value, optios strings, etc.)
    # 2. override the action's default attribute with value from
    #    config file
    for dest, value in config.items():
        # get internal action object for this argument definition
        action = get_action(parser, dest, fail_if_missing=False)
        if action is None:
            # no action for this config file key indicates error:
            # config file keys should be 'dest' names (and each
            # dest should return an action)
            valid_dests = get_dests(parser)
            print(
                f"{RED}Unknown key in config file '{dest}'. "
                f"Valid keys: {', '.join(valid_dests)}{RESET}",
                file=sys.stderr,
            )
            sys.exit(1)
        # save copy of original default (if any)
        original_default = action.default
        # overwrite with config file value
        action.default = value
        # save original for future reference
        action.default_original = original_default
        # denote that config applied
        action.config = True


def dump_args(parser, args):
    """
    Debug function for dumping args in an argparser parser
    Must call parse_args before calling (else nothing will
    print as parser._actions will be empty)

    Example:
        >>>    parser = argparse.ArgumentParser()
        >>>    parser.add_argument("-p", "--project")
        >>>    args = parser.parse_args()
        >>>    dump_args(parser, args)
    """
    for action in parser._actions:
        # get list of CLI args that map to
        # this action (e.g. ['--project', '-p'])
        option_strings = action.option_strings
        dest = action.dest
        if not hasattr(args, dest):
            continue
        was_supplied_cli = user_supplied(parser, option_strings[0])
        was_supplied_config = config_supplied(parser, option_strings[0])
        original_str = ""
        if was_supplied_config:
            original_default = get_original_default(parser, option_strings[0])
            original_str = (
                f"{ITALIC}{MAGENTA}original 'default' : {original_default}{RESET}\n"
            )

        default = parser.get_default(dest)
        value = getattr(args, dest)
        col1_prefix = f"{YELLOW}{BOLD}"
        print(
            f"----------------------------\n"
            f"{BLUE}{', '.join(option_strings)}\n"
            f"{col1_prefix}dest{RESET}               : {dest}\n"
            f"{col1_prefix}default{RESET}            : {default}\n"
            f"{col1_prefix}value{RESET}              : {value}\n"
            f"{col1_prefix}supplied (CLI)?{RESET}    : {was_supplied_cli}\n"
            f"{col1_prefix}supplied (config)?{RESET} : {was_supplied_config}\n{original_str}"
            f"{RESET}"
            f"---------------------------\n",
            flush=True,
        )


# ============================================================================
# MAIN DRIVER
# ============================================================================


def get_projects_data(project_paths, sort_by, sort_reverse):
    """
    Takes a list of filepaths to SmartEdit Writer projects and returns a list of
    dicts with the project data (name and root Node of tree with scene mapping)

    The tree includes all folders and scenes in Section 1 (manuscript),
    ordered by their DisplayTrees.Position.

    Args:
        project_paths (list[Path]): List of absolute Paths to SmartEdit Writer
            project directories.
        sort_by (str): Name of the Node attribute to sort children by.
        sort_reverse (bool): True sorts descending, False ascending.
            Passed to list.sort()'s reverse parameter.

    Returns:
        list[dict]: A list of project data dicts, each with keys:
            - "name" (str): The project directory name.
            - "tree" (Node): Root Node of the project's manuscript tree.
    """
    projects_data = []
    for proj_path in project_paths:
        # Resolve to handle symlinks, rel paths.
        proj_path = proj_path.resolve()
        proj_name = proj_path.name
        project_tree = db_info(proj_path, sort_by, sort_reverse)
        projects_data.append({"name": proj_name, "tree": project_tree})
    return projects_data


def main():
    """
    Collect user params and call db_info passing those params.
    """

    # -----------------------------------------------------------
    # Create main argparse parser
    # -----------------------------------------------------------

    parser = argparse.ArgumentParser(
        description="Print db data for SmartEdit Writers",
        # must supply add_help=False else --help will
        # only supply args added in stage 1
        # add it in manually in stage 2
        add_help=False,
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    # ===========================================================
    # CLI parsing Stage 1:
    # ===========================================================
    # Config file only (allows you to get the config file and apply
    # its specified defaults to remaining args)
    # ===========================================================

    # stage 1: get config file
    parser.add_argument(
        "--config-file",
        type=Path,
        default=CONFIG_FILE_DEFAULT,
        help=f"Optional config file for script.",
    )
    args, _ = parser.parse_known_args()

    # -----------------------------------------------------------
    # Check for TOML config file; parse it (but don't yet apply)
    # -----------------------------------------------------------

    # check if config toml file
    toml_dict = None
    if args.config_file:
        toml_config_path = args.config_file.resolve(strict=False)
        if toml_config_path.exists():
            print(
                f"\n{BOLD}{YELLOW}Script config file detected: {BLUE}{toml_config_path}{RESET}"
            )
            try:
                with open(toml_config_path, "rb") as f:
                    toml_dict = tomllib.load(f)
            except Exception as e:
                print(
                    f"{RED}Error parsing config file {toml_config_path}: {e}{RESET}",
                    file=sys.stderr,
                )
                sys.exit(1)
        else:
            if user_supplied(parser, "--config-file"):
                print(
                    f"{RED}--config-file {args.config_file} error: File doesn't exist -- {toml_config_path}{RESET}",
                    file=sys.stderr,
                )
                sys.exit(1)

    # ===========================================================
    # CLI parsing Stage 2:
    # ===========================================================
    # - Define remaining CLI flags + defaults
    # - apply config file values to overwrite defaults
    # - parse
    # ===========================================================

    # stage 2: remaining args

    # (add --help manually in step 2 as argparse's default
    # built in --help had to be declined in stage 1 else
    # --help would have only shown stage 1 args)
    parser.add_argument("-h", "--help", action="help")
    parser.add_argument(
        "-p",
        "--project",
        required=False,
        type=Path,
        nargs="+",
        help="SmartEdit Project Directory (if not supplied, will find all SmartEdit projects in user's Documents directory and then prompt for selection)",
    )
    parser.add_argument(
        "--search-root",
        required=False,
        type=Path,
        default=SEARCH_ROOT,
        help=f"Directory to search for SmartEdit projects in. Ignored if --project is supplied.",
    )
    parser.add_argument(
        "--norecursive",
        required=False,
        default=False,
        action="store_true",
        help="When --project is omitted and SmartEdit projects are searched for, make the search non-recursive (quicker, but could miss projects)",
    )
    parser.add_argument(
        "-s",
        "--short",
        required=False,
        default=False,
        action="store_true",
        help="print filenames only, not complete paths",
    )
    parser.add_argument(
        "--sort",
        required=False,
        type=str,
        default="position",
        choices=SORT_KEYS,
        help=f"Sort tree by Node attribute. Valid keys: {', '.join(SORT_KEYS)}.",
    )
    parser.add_argument(
        "--sort-order",
        required=False,
        type=str,
        default="asc",
        choices=["asc", "desc"],
        help="Sort order: asc or desc.",
    )
    parser.add_argument(
        "--html",
        required=False,
        default=False,
        action="store_true",
        help="make HTML file (else prints to console)",
    )
    parser.add_argument(
        "--merge",
        action="store_true",
        help="Merge projects into a single report (else will create individual reports)",
    )
    parser.add_argument(
        "--browser",
        action="store_true",
        help="Open generated HTML report(s) in user's default browser upon completion",
    )
    parser.add_argument(
        "--output",
        required=False,
        type=Path,
        default=DEFAULT_HTML_REPORT_DIR,
        help=f"Output path for HTML report or JSON file. Must supply --html.",
    )
    parser.add_argument(
        "--html-output",
        required=False,
        type=Path,
        default=DEFAULT_CONVERTED_DIR,
        help=f"Output path for converted HTML files. Must supply --html and --convert.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite the HTML report if it already exists",
    )
    parser.add_argument(
        "--force-assets",
        action="store_true",
        help="Overwrite existing assets/ directory at the output location. Use if "
        "you've updated the script's default assets (CSS, JS, favicon) and want the "
        "output directory to reflect those changes.",
    )
    parser.add_argument(
        "--force-html",
        action="store_true",
        help="Overwrite existing converted HTML files. Requires --convert.",
    )
    parser.add_argument(
        "--nuclear",
        action="store_true",
        help="USE AT YOUR OWN RISK. Force delete existing assets/ dir by removing "
        "read-only permissions. Only use if --force-assets fails with 'Access denied'.",
    )
    parser.add_argument(
        "--convert",
        action="store_true",
        help="Convert .docx and .rtf source files to HTML for inline viewing in the report.",
    )
    parser.add_argument(
        "--reuse",
        action="store_true",
        help="Reuse previously converted HTML files when they already exist, skipping reconversion. Files that don't exist yet will still be converted.",
    )
    parser.add_argument(
        "--style",
        required=False,
        default="default",
        choices=sorted(CONVERTED_STYLES.keys()) + ["none"],
        help=f"CSS style for converted HTML files.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help=f"Print project tree to JSON.",
    )
    parser.add_argument(
        "--json-out",
        action="store_true",
        help=f"Write JSON to a file.",
    )
    parser.add_argument(
        "--json-file",
        required=False,
        type=Path,
        default=DEFAULT_JSON_FILE,
        help=f"Save JSON serialized project tree to this file (requires --json-out).",
    )
    parser.add_argument(
        "--json-indent",
        type=int,
        default=2,
        help=f"Number of spaces for JSON indentation. Use 0 for compact output.",
    )
    parser.add_argument("--version", "-v", action="version", version=f"{__version__}")

    # -----------------------------------------------------------
    # Apply TOML config data as parser defaults
    # -----------------------------------------------------------

    # apply TOML config data before final parse
    if toml_dict:
        # integrate config file to defaults
        apply_config(parser, toml_dict)
        print(f"{BOLD}{YELLOW}Settings applied from config file{RESET}.", flush=True)

    args = parser.parse_args()

    # -----------------------------------------------------------
    # Update parser defaults based on other arguments parsed
    # -----------------------------------------------------------

    # update default --html-output (dir holding converted HTML files)
    # for user-supplied --output (nest in user-supplied output dir)
    # (Do NOT overwrite user supplied --html-output !)
    if any_supplied(parser, "--output") and not any_supplied(parser, "--html-output"):
        setattr(args, "html_output", args.output / DEFAULT_CONVERTED_DIRNAME)

    # update default --json-file for user-supplied --output (nest in it)
    if any_supplied(parser, "--output") and not any_supplied(parser, "--json-file"):
        setattr(args, "json_file", args.output / DEFAULT_JSON_FILENAME)

    # -----------------------------------------------------------
    # Validate Mutually Exclusive args
    # -----------------------------------------------------------
    #
    # Why some of these checks mix user_supplied(parser, argument)
    # and args.argument
    #
    # This allows differentiation between args supplied directly on CLI
    # vs argparse defaults (including toml config file values applied to
    # those defaults)
    #
    # Example: user SHOULD be able to specify "merge=true" or "convert=true"
    # in their config file to indicate "if I'm building HTML reports, always
    # merge / always generate HTML from src files. In such cases, should NOT
    # fail if --html not supplied. However, if user supplied --merge on the
    # CLI and not --html -- this IS is a problem
    # -----------------------------------------------------------

    if user_supplied(parser, "--merge") and not args.html:
        print(
            f"{RED}--merge without --html: --merge specifies if --html reports should be merged{RESET}",
            file=sys.stderr,
        )
        sys.exit(1)
    if user_supplied(parser, "--browser") and not args.html:
        print(f"{RED}--browser is only used with --html{RESET}", file=sys.stderr)
        sys.exit(1)
    if user_supplied(parser, "--convert") and not args.html:
        print(f"{RED}--convert is only used with --html{RESET}", file=sys.stderr)
        sys.exit(1)
    if user_supplied(parser, "--output") and not args.html:
        print(f"{RED}--html required for --output{RESET}", file=sys.stderr)
        sys.exit(1)
    if user_supplied(parser, "--html-output") and not args.html:
        print(f"{RED}--html required for --html-output{RESET}", file=sys.stderr)
        sys.exit(1)
    if user_supplied(parser, "--html-output") and not args.convert:
        print(f"{RED}--convert required for --html-output{RESET}", file=sys.stderr)
        sys.exit(1)
    if user_supplied(parser, "--json-file") and not args.json_out:
        print(
            f"{RED}--json-file requires --json-out (the trigger to write JSON to file){RESET}",
            file=sys.stderr,
        )
        sys.exit(1)

    # -----------------------------------------------------------
    # Validate --sort
    # -----------------------------------------------------------

    # a defensive check: ensure --sort (including defaults) are valid
    # attributes of Node objects. (Node's add_child function is what
    # performs the sort, and it sorts on its own parameters.)
    if args.sort:
        # Create a throwaway instance to check instance attributes
        dummy = Node(name="", id=None, type=None, section=None)
        if not hasattr(dummy, args.sort):
            print(
                f"{RED}--sort value '{args.sort}' isn't a valid Node attribute. "
                f"This should not happen: Please file a bug report with this message. "
                f"Either: (1) Node's attribute names changed (2) SORT_KEYS was "
                f"updated to include a key that's not a Node attribute (3) argparse "
                f"--sort default changed to an invalid Node attribute{RESET}",
                file=sys.stderr,
            )
            sys.exit(1)

    # -----------------------------------------------------------
    # Determine sort order
    # -----------------------------------------------------------

    # determine sort direction.
    # (add_child will pass to python's native list.sort
    #  as reverse param, so must be a boolean)
    if args.sort_order:
        if args.sort_order == "desc":
            sort_reverse = True
        elif args.sort_order == "asc":
            sort_reverse = False
        else:
            print(
                f"{RED}Can't determine sort order from --sort-order ({args.sort_order}). "
                f"This should not happen: argparse choices must have changed. "
                f"Please file a bug report with this message.{RESET}",
                file=sys.stderr,
            )
            sys.exit(1)
    else:
        print(
            f"{RED}--sort-order wasn't defined. It should always at least have a default "
            f"assigned via argparse. Please file a bug report with this message.{RESET}",
            file=sys.stderr,
        )
        sys.exit(1)

    # -----------------------------------------------------------
    # Validate --project
    # -----------------------------------------------------------
    if args.project:
        for project in args.project:
            if not project.exists():
                print(
                    f"{RED}--project doesn't exist ({project}){RESET}", file=sys.stderr
                )
                sys.exit(1)
            if not project.is_dir():
                print(
                    f"{RED}--project isn't a directory ({project}){RESET}",
                    file=sys.stderr,
                )
                sys.exit(1)

    # -----------------------------------------------------------
    # Validate --search-root
    # -----------------------------------------------------------
    if not args.search_root.exists():
        print(
            f"{RED}--search-root doesn't exist ({args.search_root}){RESET}",
            file=sys.stderr,
        )
        sys.exit(1)
    if not args.search_root.is_dir():
        print(
            f"{RED}--search-root isn't a directory ({args.search_root}){RESET}",
            file=sys.stderr,
        )
        sys.exit(1)

    # -----------------------------------------------------------
    # Validate --output
    # -----------------------------------------------------------
    if user_supplied(parser, "--output") and args.output.is_file():
        # --output is an existing dir (Path.is_file() returns False if Path doesn't exist)
        print(
            f"{RED}--output must be a directory. It was a file ({args.output}){RESET}",
            file=sys.stderr,
        )
        sys.exit(1)

    # -----------------------------------------------------------
    # Validate --html-output
    # (location to copy converted HTML files to)
    # -----------------------------------------------------------
    if user_supplied(parser, "--html-output") and args.html_output.is_file():
        # --html-output is an existing file (Path.is_file() returns False if Path doesn't exist)
        print(
            f"{RED}--html-output must be a dir, not a file: {args.html_output}{RESET}",
            file=sys.stderr,
        )
        sys.exit(1)

    # -----------------------------------------------------------
    # validate --style for converted HTML files
    # -----------------------------------------------------------
    if args.style:
        if args.style.lower() == "none":
            converted_css = ""
        else:
            if args.style not in CONVERTED_STYLES:
                raise Exception(
                    f"{args.style} not in CONVERTED_STYLES: logic around --style validation in argparse "
                    "must have changed (choices should be keys of CONVERTED_STYLES)"
                )
            converted_css = CONVERTED_STYLES[args.style]

    # -----------------------------------------------------------
    # Resolve Output Directories
    # -----------------------------------------------------------

    # Note: stict=False required or will fail if path doesn't yet exist
    search_root = args.search_root.resolve()
    output_path = args.output.resolve(strict=False)
    html_output = args.html_output.resolve(strict=False)
    json_path = args.json_file.resolve(strict=False)

    # -----------------------------------------------------------
    # Get projects interactively (if --project not supplied)
    # -----------------------------------------------------------

    # if --project not given, will scan all projects in search_root
    # and prompt user to select one. Get their initial selection.
    proj_paths = args.project
    projects = []
    if not proj_paths:
        # projects is a list of filepaths to SmartEdit Writer projects
        projects, proj_paths = get_projects_interactively(
            search_root, not args.norecursive
        )

    # -----------------------------------------------------------
    # Query SQLite project Databases and generate project trees
    # -----------------------------------------------------------

    # collect info for set of projects
    projects_data = get_projects_data(proj_paths, args.sort, sort_reverse)

    # -----------------------------------------------------------
    # Provide results based on user request (stdout, HTML report(s), JSON, etc.)
    # -----------------------------------------------------------

    # print tree(s) to stdout (only if not html, json options)
    console = True

    if args.html:
        # --html flag: Generate static HTML report
        create_HTML_reports(
            projects=projects_data,
            template=TEMPLATE,
            short=True,
            assets_src=ASSETS_SRC,
            converted_css=converted_css,
            output=output_path,
            html_output=html_output,
            force=args.force,
            force_assets=args.force_assets,
            force_html=args.force_html,
            nuclear=args.nuclear,
            tree_icons=TREE_ROOT_ICON_CLASSES,
            merge=args.merge,
            browser=args.browser,
            convert=args.convert,
            reuse=args.reuse,
        )
        console = False

    if args.json or args.json_out:
        # --json flag: print data as JSON
        print_projects_json(
            projects=projects_data,
            short=args.short,
            indent=args.json_indent,
            console=args.json,
            output=json_path if args.json_out else None,
            force=args.force,
        )
        console = False

    if console:
        # print tree to stdout
        print_projects(projects_data, args.short)


if __name__ == "__main__":
    main()
