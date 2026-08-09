"""
Finds the source files for scenes in a SmartEdit Writer project
and displays them either on stdout or in an HTML file.

Usage:
    python db_read.py [--project PROJECT] [--short] [--html]

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
import argparse
import webbrowser
import sqlite3
import shutil
import copy
import stat
import string
from bs4 import BeautifulSoup
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent  # path of py script
sys.path.insert(1, str(SCRIPT_DIR / "libs"))

import beautiful_soup_utils

TEMPLATE = SCRIPT_DIR / "template.html"
SOUP = BeautifulSoup("", "html.parser")

# if user doesn't supply --project, will search
# for SmartEdit projects and prompt for user selection.
# SEARCH_ROOT is default location to start search in.
# Defaults to the user's Documents folder;
# modify this if your SmartEdit Writer projects
# are stored elsewhere
# (search root overridden via --search-root arg)
SEARCH_ROOT = Path.home() / "Documents"
# default path for HTML reports (overridden by --output)
DEFAULT_HTML_REPORT_DIR = Path.cwd()
DEFAULT_HTML_REPORT_FILENAME = "report.html"
# source assets/ directory that static reports rely on
ASSETS_SRC = SCRIPT_DIR / "assets"
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
        name: UserDefinedName from MetaData (display name in the UI).
        id: MetaData.ID (database primary key, also used for filenames).
        type: MetaData.ItemType (0=root, 1=folder, 2=scene, 3=note, etc.).
        position: DisplayTrees.Position (ordinal among siblings).
        source: Path to the on-disk file, or None if not file-backed.
        parent: Parent Node, or None for the root.
        children: List of child Nodes, maintained in Position order.
    """

    def __init__(self, name, id, type, position=0, source=None, parent=None):
        self.name = name
        self.id = id
        self.type = type
        self.position = position
        self.source = source
        self.parent = parent
        self.children = []

    def add_child(self, child):
        """Insert child and maintain Position order among siblings."""
        child.parent = self
        self.children.append(child)
        self.children.sort(key=lambda n: n.position)

    def __repr__(self):
        return (
            f"Node(name={self.name!r}, id={self.id}, type={self.type}, "
            f"position={self.position}, children={len(self.children)})"
        )


def print_tree(node, indent=0):
    """
    Print a Node tree to stdout for debugging.

    Displays each node's name, type, position, and source file (if any)
    in an indented tree format. Children are printed in their stored order.

    Args:
        node: Root Node of the tree (or subtree) to print.
        indent: Current indentation level (used internally for recursion).
    """
    spacer = "    " * indent

    # Determine icon for visual distinction
    if node.type == 1:
        icon = "+"  # folder
    elif node.type == 2:
        icon = "-"  # scene
    elif node.type == 3:
        icon = "~"  # note
    elif node.type is None:
        icon = "#"  # synthetic root
    else:
        icon = "?"  # unknown type

    # Build the line: icon, name, metadata
    parts = [f"{spacer}{icon} {node.name}"]
    meta = []
    if node.id is not None:
        meta.append(f"id={node.id}")
    if node.type is not None:
        meta.append(f"type={node.type}")
    meta.append(f"pos={node.position}")
    if node.source is not None:
        meta.append(f"source={node.source.name}")
    if meta:
        parts.append(f"  ({', '.join(meta)})")

    print("".join(parts))

    for child in node.children:
        print_tree(child, indent + 1)


# ItemTypes that have a corresponding file on disk.
# Used by db_info() to determine whether a Node should have a source path.
# 2 = scene (.docx), 3 = note (.rtf) — add 3 when note support is enabled.
FILE_BACKED_TYPES = frozenset({2})


# ============================================================================
# GENERAL UTILITY FUNCTIONS
# ============================================================================


def generate_random_alphanumeric(length):
    """
    Generate a random string of alphanumeric characters.

    Used as a fallback when safe_name() is given a string with no
    alphanumeric content and cannot produce a meaningful name.

    :param int length: number of characters in the returned string
    :returns str: a random string of letters and digits
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

    :param str name: the original string (e.g. a project name)
    :returns str: a sanitized version suitable for directory names

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
    """Checks if two Paths are the same, assuming they might not exist
    :param Path path1: First Path
    :param Path path2: Second Path
    :returns bool True if same, else False
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

    Raises:
        FileExistsError: If force and nuclear are both False and path exists.

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

    :param Path search_root: root directory to begin searching for SmartEdit Writer projects
    :param bool recursive: do a recursive search for SmartEdit projects.
    :returns list[Path]: list of abs paths
        to SmartEdit Writer projects found
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

    :param str selection_str: raw input string from the user
    :returns tuple[list[int], list[str]]: (selections, errors) where
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

    :param list[Path] projects: list of abs filepaths to SmartEdit Writer
        projects to display to the user.
    :returns list[Path]: abs path to the selected SmartEdit Writer projects
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

    :param Path search_root: root directory to begin searching for SmartEdit Writer projects
    :param bool recursive: do a recursive search for SmartEdit projects.
    :returns:
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


def db_info(proj_path):
    """
    Build a tree of Node objects representing the project structure.

    Queries MetaData and DisplayTrees to construct the full hierarchy
    for Section 1 (manuscript). Includes folders (ItemType=1) as
    structural nodes and scenes (ItemType=2) as file-backed leaves.
    Children are ordered by DisplayTrees.Position, matching the
    SmartEdit Writer UI.

    Args:
        proj_path: Absolute path to the SmartEdit Writer project
            directory (the parent of .atomic and Documents).

    Returns:
        Node: The root node of the project tree. Its children are the
            top-level items in the manuscript section.
    """

    db_path = proj_path / ".atomic" / "atomic.meta"  # project db
    doc_path = proj_path / "Documents"  # dir with src files

    con = sqlite3.connect(str(db_path))
    cur = con.cursor()

    # Single query: all items in the section with their tree metadata.
    # Folders (ItemType=1) are included so the full hierarchy is
    # captured, not just file-backed leaves.
    cur.execute("""
        SELECT m.ID, m.UserDefinedName, m.ItemType, dt.ParentId, dt.Position
        FROM MetaData m
        JOIN DisplayTrees dt ON m.ID = dt.ItemId
        WHERE m.Section = 1
          AND m.Status = 1
          AND m.ItemType IN (1, 2)
        ORDER BY dt.ParentId, dt.Position
    """)
    rows = cur.fetchall()

    cur.close()
    con.close()

    # --- Build all nodes and record parent references ---
    nodes = {}
    parent_map = {}  # obj_id -> parent_id

    for obj_id, name, item_type, parent_id, position in rows:
        source = None
        if item_type in FILE_BACKED_TYPES:
            source = file_from_id(obj_id, doc_path)

        nodes[obj_id] = Node(
            name=name,
            id=obj_id,
            type=item_type,
            position=position,
            source=source,
        )
        parent_map[obj_id] = parent_id

    # --- Link parents to children ---
    # Items with ParentId=0 are top-level under the section root.
    # Items whose parent_id points to a node not in our set (e.g.,
    # a parent filtered out by ItemType) also go under root.
    root = Node(name="Project", id=None, type=None, position=0)

    for obj_id, node in nodes.items():
        parent_id = parent_map[obj_id]
        if parent_id == 0 or parent_id not in nodes:
            root.add_child(node)
        else:
            nodes[parent_id].add_child(node)

    return root


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
        obj_id: ID of the item in the MetaData table.
        cur: SQLite cursor for the project database.

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
        obj_id: ID of the item in the MetaData table.
        cur: SQLite cursor for the project database.

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
        obj_id: ID of the item in the MetaData table.
        cur: SQLite cursor for the project database.

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


def file_from_id(obj_id, doc_path):
    """
    given an id in the sqlite db,
    return the filepath for that obj

    :param int obj_id: id of the object in the sqlite db
    :param Path doc_path: absolute path to the Documents directory
        for the SmartEdit Writer project
    :returns Path: path to the .docx file for the given object
    """
    return doc_path / f"{obj_id}.docx"


# ============================================================================
# STDOUT PRINTING
# ============================================================================


PROJ_SEP = "─"
TITLE_SEP = ". "
SEP_LENGTH = 50


def _print_separator(separator):
    # how many separators to print based on sep length
    num_seps = int(SEP_LENGTH / len(separator))
    print(separator * num_seps)


def _line_separator():
    _print_separator(TITLE_SEP)


def _proj_separator():
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


def _max_name_width(node):
    """Find the length of the longest name in the tree (for alignment)."""
    max_len = len(node.name)
    for child in node.children:
        max_len = max(max_len, _max_name_width(child))
    return max_len


def print_project_tree(node, short, d=0, name_width=0, prefix=""):
    """
    Print a Node tree to stdout with modern formatting.

    Uses emoji icons and box-drawing characters for tree structure.
    Source file paths are aligned to a consistent column after names.

    Args:
        node: Node object for the current tree position.
        short: If True, display only filenames, not full paths.
        d: Indentation depth (used internally for recursion).
        name_width: Width of the longest name in the tree, used to
            align source file paths. Computed on the root call.
        prefix: String prefix for tree connectors (used internally
            for recursion).
    """
    FOLDER_ICON = "📁"
    SCENE_ICON = "📄"
    NOTE_ICON = "🗃️"
    PROJECT_ICON = "📚"

    if d == 0 and name_width == 0:
        name_width = _max_name_width(node)

    # Determine icon
    if node.type is None:
        icon = PROJECT_ICON
    elif node.type == 1:
        icon = FOLDER_ICON
    elif node.type == 2:
        icon = SCENE_ICON
    elif node.type == 3:
        icon = NOTE_ICON
    else:
        icon = "•"

    # Build the line (no connector prefix for root)
    if d == 0:
        line = f"{icon} {node.name}"
    else:
        line = f"{prefix}{icon} {node.name}"

    # Append source file for leaf nodes
    if node.source and not node.children:
        source_path = node.source.name if short else str(node.source)
        padding = " " * (name_width - len(node.name) + 2)
        line += f"{padding}→  {source_path}"

    print(line)

    # Recurse into children with updated prefix
    for i, child in enumerate(node.children):
        is_last = (i == len(node.children) - 1)
        if d == 0:
            # Children of root: start a new prefix
            connector = "└─ " if is_last else "├─ "
            child_prefix = connector
        else:
            connector = "└─ " if is_last else "├─ "
            # For the vertical lines: keep parent's prefix but switch
            # the last connector character
            child_prefix = prefix[:-3] + ("   " if prefix.endswith("└─ ") else "│  ") + connector
        print_project_tree(child, short, d + 1, name_width, child_prefix)


# ============================================================================
# HTML TREE GENERATION (BEAUTIFULSOUP)
# ============================================================================


def make_tree(tree, short, icon_tree_root):
    """
    Creates HTML for a nested <ul> tree containing
    the mapping of scenes and their source files.

    :param Node tree: root tree Node for project generated by db_info()
    :param bool short: only display the filename of a source
        file, rather than its entire absolute path
    :param str icon_tree_root: CSS class for icon to use for tree root
    :returns: BeautifulSoup Tag (a <ul class="tree"> element)
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
        parent_ul: BeautifulSoup Tag — the <ul> to append <li> children to.
        curr_node: Node object representing the current tree position.
        short: If True, display only filenames for source links.
        icon_tree_root: CSS class for the root node's icon.
        expandable: Whether nodes at this level should be collapsible.
            Set to False for the root to exclude it from Expand All /
            Collapse All controls.
    """

    # Render current node
    li = build_li(
        node=curr_node,
        short=short,
        expandable=expandable,
        is_root=not expandable,
        icon_tree_root=icon_tree_root,
    )
    parent_ul.append(li)

    # Render all children (if any) inside current node's <li>
    if curr_node.children:
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
    is_root,
    icon_tree_root,
):
    """
    Build an <li> for a tree node (leaf, folder, scene-with-children, or root).

    :param Node node: Node in project tree to build the <li> for
    :param bool short: show only the filename, not the full path
    :param bool expandable: whether the node should be collapsible
    :param bool is_root: whether this is the root project node
    :param str icon_tree_root: CSS class for the root icon
    :returns: BeautifulSoup Tag (<li>)
    """

    name = node.name
    source = node.source
    node_type = node.type
    has_children = bool(node.children)
    is_leaf = not has_children

    li = SOUP.new_tag("li")
    li["class"] = _build_node_classes(
        node_type, has_children, expandable, is_root, is_leaf
    )

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


def _build_node_classes(
    node_type, has_children, expandable=True, is_root=False, is_leaf=False
):
    """
    Build the list of CSS classes for a tree-node <li>.

    :param int node_type: 1 = folder, 2 = scene
    :param bool has_children: whether the node contains sub-items
    :param bool expandable: whether the node should be collapsible
        via Expand All / Collapse All and click-to-toggle. Nodes
        with children but expandable=False (e.g. the root) still
        get .has-children but omit .expandable and the twistie.
    :param bool is_root: whether the node is the tree root
    :param bool is_leaf: whether the node is a leaf root
    :returns: list of class name strings
    """
    classes = ["tree-node"]
    if node_type == 1:
        classes.append("folder-node")
    else:
        classes.append("scene-node")
    if has_children:
        classes.append("has-children")
        if expandable:
            classes.append("expandable")
    if is_root:
        classes.append("tree-root")
    if is_leaf:
        classes.append("leaf-scene")
    return classes


def count_leaves(node):
    """
    Count the total number of leaves in a Node tree.

    A leaf is any node with no children and a non-None source file.
    These are the terminal items with on-disk documents.

    Args:
        node: Root Node of the tree (or subtree) to count.

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
):
    """
    Create one or more HTML reports for the given projects.

    If merge is True, all projects are combined into a single report.
    If merge is False, a separate report is generated for each project.

    Delegates to create_HTML_report() for each individual report file.

    :param list[dict] projects: list of project dicts, each with
        'name' (str) and 'tree' (dict) keys, as returned by
        get_projects_data()
    :param bool short: only display filenames of the src
        files rather than entire abs paths
    :param Path assets_src: Path where source assets/ lives.
    :param str converted_css: content of CSS for converted files
    :param Path output: path to write file(s) to. If merge is True,
        this is the output file. If merge is False, this is the
        output directory (reports named after project names).
    :param bool force: overwrite output if exists
    :param bool force_assets: If True, overwrite an existing assets/
        directory at the destination. If False and the destination
        assets/ already exists, the copy is skipped and existing
        assets are used as-is (preserving any user customizations).
    :param bool nuclear: If True, uses aggressive deletion that strips read-only
        permissions before retrying (Windows only). Implies force.
        This is used when force alone fails.
    :param list[str] tree_icons: list of CSS classes available to assign to
        root node of project (the classes should have corresponding
        rules in style.css).
    :param bool merge: Merge all projects into a single HTML report
       (if False, one report generated for each project)
    :param bool browser: Open HTML report(s) in the browser.
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
        )


def create_HTML_report(
    project_list,
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
):

    # create base file from template file
    soup = beautiful_soup_utils.make_soup_from_file(TEMPLATE, False)
    # generate BeautifulSoup for the file for list of projects
    project_soup = generate_report_content(project_list, short, tree_icons)
    # get title for <title> tag
    page_title = get_report_title(project_list)
    # get a "name" for this report
    report_name = get_report_name(project_list)
    beautiful_soup_utils.find_replace_str(soup, "%TREES%", project_soup)
    beautiful_soup_utils.find_replace_str(soup, "%TITLE%", page_title)

    # Get output path for static HTML report
    output = get_report_filepath(output, merge, project_list)

    # convert source files in the SmartEdit project to HTML and inject view links
    if convert:
        # Specify dir specific to this report to hold converted files
        report_dir = html_output / safe_name(f"report-{report_name}")
        inject_view_links(soup, report_dir, converted_css, output, force_html)

    # If output file already exists and force not given, error
    if output.exists() and not force:
        raise Exception(
            f"Output already exists: {output}. (Try re-running script with --force)"
        )

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


def get_report_filepath(output, merge, project_list):
    """
    Get the filepath for a static HTML report based
    on user selected arguments.
    """

    # if merge, use output (--merge => --output should be a filepath)
    if merge:
        return output

    # if no projects, this is a bug
    if not project_list:
        raise Exception(f"get_report_filepath: Project list is empty!")

    # if not merge case, there should only be one project,
    # and output should be a directory.
    # use project name as file within output dir
    if len(project_list) > 1:
        raise Exception(
            f"get_report_filepath: More than one project in list even though merge supplied. ({len(project_list)})"
        )

    # get name of the project
    if not "name" in project_list[0]:
        raise Exception("get_report_filepath: no name attribute on project!")
    project_name = project_list[0]["name"]

    # append to output
    return output / f"{project_name}.html"


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

    :param Path assets_src: Path to the source assets directory
    :param Path assets_dest: Path to copy assets to.
    :param bool force: If True, overwrite existing assets directory; if False, raise
        error if destination already exists.
    :param bool nuclear: If True, uses aggressive deletion that strips read-only
        permissions before retrying (Windows only). Implies force.
        This is used when force alone fails.
    :returns: None

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
                f"Assets directory already exists at {assets_dest}.\n"
                f"Skipping copy — existing assets will be used.\n"
                f"Use --force-assets to overwrite with default assets."
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


def inject_view_links(soup, output_dir, converted_css, report_path, force):
    """
    Find all source links in the BeautifulSoup tree, convert the
    referenced .docx and .rtf files to HTML, and insert view-link
    spans alongside them.

    The converted HTML files are written to output_dir. The view
    links use relative paths computed from report_path so they
    resolve correctly when the report is opened in a browser.

    :param soup: BeautifulSoup object for the HTML report
    :param Path output_dir: directory to write converted HTML files to
    :param str converted_css: content of CSS for converted files
    :param Path report_path: path where the HTML report will be written
        (used to compute relative links to converted files)
    :param bool force: if True, overwrite existing converted HTML files
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

        # returns abs path of HTML file written
        html_path = convert_source_to_html(
            source_path, project_output_dir, converted_css, force
        )

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
        content: Final HTML string.
        output: Path to write html file to
        converted_css: string content of CSS for converted files
        force: Whether to overwrite existing file.

    Returns:
        Path to file written

    Raises:
        FileExistsError: If file exists and force is False.
    """
    if output.exists() and not force:
        raise FileExistsError(
            f"HTML file {output} already exists. Use --force-html to overwrite."
        )

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


def convert_source_to_html(source_path, output_dir, converted_css, force):
    """
    Convert a .docx or .rtf source file to HTML and save it to output_dir.

    :param Path source_path: path to the .docx or .rtf file
    :param Path output_dir: directory to write the converted HTML file to
    :param str converted_css: content of CSS for converted files
    :param bool force: if True, overwrite an existing HTML file at the
        destination
    :returns Path: absolute path to the written HTML file
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

    html_path = output_dir / f"{source_path.stem}.html"
    print(f"\rConverting {source_path.name}... done. Written to {html_path}")
    return write_html_file(html, html_path, converted_css, force)


def convert_docx_to_html(filepath: Path) -> str:
    """
    Convert a .docx file to HTML, preserving headings, lists, bold/italic,
    tables, and basic structure.

    Args:
        filepath: Path to .docx file

    Returns:
        HTML string
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
        filepath: Path to .rtf file
        indent: int. Indents new lines in .txt, .rtf by this many spaces
            in final rendered HTML (overrides existing leading spaces to
            make document indentation uniform).

    Returns:
        HTML string
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
        raw_text: string to convert to HTML
        indent: int to control indentation of new lines in raw text.
            If > 0, all lines will be indented that many spaces.
            NOTE: Overrides any leading spaces currently present.

    Returns:
        HTML string with paragraphs, line breaks, and preserved leading indentation.
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
        text: The input string to modify.
        replacements: A list of [target, replacement] pairs. Each pair must
            contain exactly two strings.

    Returns:
        The transformed string after applying all replacements in order.

    Example:
        >>> sequential_replacements("ab", [["a", "b"], ["b", "a"]])
        "aa"  # Note: not "ba" due to sequential application.
    """
    for target, replacement in replacements:
        text = text.replace(target, replacement)
    return text


# ============================================================================
# MAIN DRIVER
# ============================================================================


def get_projects_data(project_paths):
    """
    Takes a list of filepaths to SmartEdit Writer projects and returns a list of
    dicts with the project data (name and root Node of tree with scene mapping)

    The tree includes all folders and scenes in Section 1 (manuscript),
    ordered by their DisplayTrees.Position.

    Args:
        project_paths: List of absolute Paths to SmartEdit Writer
            project directories.

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
        project_tree = db_info(proj_path)
        projects_data.append({"name": proj_name, "tree": project_tree})
    return projects_data


def main(args):
    """
    collect user params and call db_info
    passing those params.

    :param args: argarse object
    """

    parser = argparse.ArgumentParser(
        description="Print db data for SmartEdit Writers",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
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
        help=f"Output path for HTML report. Must supply --html.",
    )
    parser.add_argument(
        "--html-output",
        required=False,
        type=Path,
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
        "--style",
        required=False,
        default="default",
        choices=sorted(CONVERTED_STYLES.keys()) + ["none"],
        help=f"CSS style for converted HTML files.",
    )
    args = parser.parse_args(args)

    if args.merge and not args.html:
        raise Exception(
            f"--merge without --html: --merge specifies if --html reports should be merged"
        )
    if args.browser and not args.html:
        raise Exception(f"--browser is only used with --html")
    if args.convert and not args.html:
        raise Exception(f"--convert is only used with --html")

    # Validate --project
    if args.project:
        for project in args.project:
            if not project.exists():
                raise Exception(f"--project doesn't exist ({project})")
            if not project.is_dir():
                raise Exception(f"--project isn't a directory ({project})")

    # Validate --search-root
    if not args.search_root.exists():
        raise Exception(f"--search-root doesn't exist ({args.search_root})")
    if not args.search_root.is_dir():
        raise Exception(f"--search-root isn't a directory ({args.search_root})")
    search_root = args.search_root.resolve()

    # Validate --output
    if args.output and not args.html:
        raise Exception(f"--html required for --output")
    if args.output and args.merge and args.output.is_dir():
        # --output is an existing dir (Path.is_dir() returns False if Path doesn't exist)
        raise Exception(
            f"--output must be a file if --merge supplied. It was a directory. ({args.output})"
        )
    if args.output and not args.merge and args.output.is_file():
        # --output is an existing dir (Path.is_file() returns False if Path doesn't exist)
        raise Exception(
            f"--output must be a directory if --merge is not supplied. It was a file ({args.output})"
        )
    # set default output based on --merge
    output_path = args.output
    if not output_path:
        output_path = DEFAULT_HTML_REPORT_DIR
        if args.merge:
            output_path = output_path / DEFAULT_HTML_REPORT_FILENAME
    # resolve in case --output a rel path.
    # Note: stict=False required or will fail if path doesn't yet exist
    output_path = output_path.resolve(strict=False)

    # Validate --html-output
    # (location to copy converted HTML files to)
    if args.html_output and not args.html:
        raise Exception(f"--html required for --html-output")
    if args.html_output and not args.convert:
        raise Exception(f"--convert required for --html-output")
    if args.html_output and args.html_output.is_file():
        # --html-output is an existing file (Path.is_file() returns False if Path doesn't exist)
        raise Exception(f"--html-output must be a dir, not a file: {args.html_output}")
    html_output = args.html_output
    if not html_output:
        # Determine the parent directory for converted HTML files when user
        # didn't specify --html-output: depends on report output path
        # (want it to be in same dir as HTML report)
        # Issue:
        # - output_path is a file when --merge is given, a directory otherwise.
        # - We branch on args.merge to match this, but this duplicates the logic
        #   above for setting the default value of output_path when --output not given
        # - If that logic ever changes, this branch must be updated too.
        parent_dir = output_path.parent if args.html and args.merge else output_path
        html_output = parent_dir / "html"
    # resolve in case --html-output a rel path.
    # Note: stict=False required or will fail if path doesn't yet exist
    html_output = html_output.resolve(strict=False)

    # validate --style for converted HTML files
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

    # if --project not given, will scan all projects in search_root
    # and prompt user to continuously select one until they select
    # option 0 (exit criteria). Get their initial selection.
    proj_paths = args.project
    projects = []
    if not proj_paths:
        # projects is a list of filepaths to SmartEdit Writer projects
        projects, proj_paths = get_projects_interactively(
            search_root, not args.norecursive
        )

    # Continue prompting user to select a project unless:
    # 1. they select option 0 (exits in chose_projects)
    # 2. --project was given (exits after first iteration)
    # 3. --html was given (exits after first iteration)
    while True:
        # collect info for set of projects
        projects_data = get_projects_data(proj_paths)
        if args.html:
            create_HTML_reports(
                projects=projects_data,
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
            )
        else:
            print_projects(projects_data, args.short)

        if args.project or args.html:  # --project given, don't ask again
            sys.exit(0)

        # ask user to select another project
        proj_paths = chose_projects(projects)


if __name__ == "__main__":
    args = sys.argv[1:]
    main(args)
