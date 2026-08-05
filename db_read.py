"""
Finds the source files for scenes in a SmartEdit Writer project
and displays them either on stdout or in an HTML file.

Usage:
    python db_read.py [--project PROJECT] [--short] [--remove] [--html]

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
    --remove:
        don't display project name in the tree
        (note: the project name is in tree for Scenes in
        the main UI -- as opposed to fragments, research.
        Currently, this project is only getting the Scenes
        in the main UI so displaying the proj name isn't
        useful, but if ever start getting scenes from fragments,
        etc, the proj name is the way to differentiate)
"""

import sys
import os
import random
import argparse
import webbrowser
import sqlite3
import shutil
import copy
import stat
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
FILE_ICON = "-"  # for displaying scene tree on stdout
FOLDER_ICON = "+"  # ""
# default path for HTML reports (overridden by --output)
DEFAULT_HTML_REPORT_PATH = Path.cwd() / "report.html"
# source assets/ directory that static reports rely on
ASSETS_SRC = SCRIPT_DIR / "assets"
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


def chose_project(projects):
    """
    displays a numbered list of SmartEdit Writer projects
    and prompts user to select one, then returns selected
    project

    :param list[Path] projects: list of abs filepaths to SmartEdit Writer
        projects to display to the user.
    :returns Path: abs path to the selected SmartEdit Writer project
    """
    for idx, project in enumerate(projects):
        print(f"[{idx + 1}] : {project}")
    while True:
        num = int(
            input(
                f"\nPlease select project number 1 - {len(projects)} (enter 0 to exit): "
            )
        )
        if num < 0 or num > len(projects):
            print(
                f"Invalid project number ({num}). You must enter a valid project number (1 - {len(projects)})"
            )
        elif num == 0:
            sys.exit(0)
        else:
            return projects[num - 1]


def get_project_interactively(search_root, recursive):
    """
    Finds all SmartEdit Writer projects on the file
    system and prompts user to select one.

    :param Path search_root: root directory to begin searching for SmartEdit Writer projects
    :param bool recursive: do a recursive search for SmartEdit projects.
    :returns list[Path], Path:
        list[Path]: the list of abs paths of all SmartEdit Writer
            projects found on the system.
        Path: the abs path to the project selected by the user
    """
    print("\nfinding SmartEdit Writer projects...\n", flush=True)
    projects = find_projects(search_root, recursive)
    if not projects:
        print(
            f"No SmartEdit projects could be found in {search_root}! (Try supplying --search-root to specify a search root, or omitting --no-recursive, to allow for a recursive search)"
        )
        sys.exit(1)
    chosen = chose_project(projects)
    return projects, chosen


def max_length(scenes):
    """
    in a list of scenes, get length
    of longest scene

    :param list[str] scenes: a list of
        scene names
    :return int: length of longest scene name
    """
    max_name = 0
    for scene in scenes:
        if len(scene) > max_name:
            max_name = len(scene)
    return max_name


def print_scenes(curr_tree, proj_name, short):
    print("\n===========================")
    print(f"    {proj_name}:\n")
    print_scene_tree(curr_tree, short, d=0)
    print("===========================\n")


def make_tree(tree, proj_name, short, icon_tree_root):
    """
    Creates HTML for a nested <ul> tree containing
    the mapping of scenes and their source files.

    Replaces the old table-based approach with semantic
    nested lists.  Each node in the tree is an <li> with
    classes indicating its type and whether it has children.

    :param dict tree: the mapping generated by db_info()
    :param str proj_name: name of the project (unused but kept
        for signature compatibility with the old make_table)
    :param bool short: only display the filename of a source
        file, rather than its entire absolute path
    :param str icon_tree_root: CSS class for icon to use for tree root
    :returns: BeautifulSoup Tag (a <ul class="tree"> element)
    """
    root_ul = SOUP.new_tag("ul")
    root_ul["class"] = "tree"
    make_tree_recursive(root_ul, tree, short, icon_tree_root, False)
    return root_ul


def make_tree_recursive(parent_ul, curr_tree, short, icon_tree_root, expandable=True):
    """
    Recursively build nested <ul>/<li> elements from the
    scene mapping dictionary.

    Processing order at each level:
      1. Any scenes in the "root" bucket (leaf items at this level)
      2. Named sub-nodes (folders or scenes that contain children)

    A node renders as a collapsible container if its 'children'
    dict has any keys other than an empty "root" list.  Both
    folders (type 1) and scenes (type 2) can be containers.

    :param parent_ul: BeautifulSoup Tag — the <ul> to append
        <li> children to
    :param dict curr_tree: the current subtree from the mapping
    :param bool short: display only filenames for source links
    :param str icon_tree_root: CSS class for icon to use for tree root
    :param bool expandable: whether nodes at this level should be
        collapsible (gets the .expandable CSS class and a twistie
        arrow). Set to False for the root node to exclude it from
        Expand All / Collapse All, keeping the first level of
        content visible as a useful overview.
    """
    # --- 1. Leaf scenes in the "root" bucket ---
    root_scenes = curr_tree.get("root", [])
    for filepath, scene_name in root_scenes:
        li = build_leaf_li(scene_name, filepath, short)
        parent_ul.append(li)

    # --- 2. Named sub-nodes (folders, or scenes with children) ---
    for key in sorted(curr_tree.keys()):
        if key == "root":
            continue

        node_data = curr_tree[key]
        node_type = node_data["type"]  # 1 = folder, 2 = scene
        node_source = node_data.get("source")
        children = node_data.get("children", {})

        # Determine if this node has actual child content beyond an
        # empty "root" bucket.
        has_children = _node_has_visible_children(children)

        # check if tree root
        is_root = not expandable and has_children

        li = SOUP.new_tag("li")
        li["class"] = _build_node_classes(node_type, has_children, expandable, is_root)

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

        # Twistie arrow (only meaningful if the node has children)
        # (actual arrow controlled via CSS ::before)
        if expandable:
            twistie = SOUP.new_tag("span")
            twistie["class"] = "twistie"
            # twistie.string = "▶"
            content_div.append(twistie)

        # Icon
        icon_span = SOUP.new_tag("span")
        if is_root:
            # tree roots get special icons
            icon_span["class"] = ["icon", icon_tree_root]
        else:
            icon_span["class"] = "icon"
        # Icon text is set via CSS ::before using data-type;
        # we keep the span empty and let CSS handle it.
        content_div.append(icon_span)

        # Name
        name_span = SOUP.new_tag("span")
        name_span["class"] = "name"
        name_span.string = key
        content_div.append(name_span)

        # Source link (shown for scenes that have a file, whether
        # or not they also act as containers)
        if node_source:
            display_path = Path(node_source).name if short else str(node_source)
            file_uri = "file:///" + str(node_source)
            link = SOUP.new_tag("a", href=file_uri)
            link["class"] = "source-link"
            link["target"] = "_blank"
            link.string = display_path
            content_div.append(link)

        li.append(content_div)

        # --- Recurse into children ---
        if has_children:
            child_ul = SOUP.new_tag("ul")
            make_tree_recursive(child_ul, children, short, icon_tree_root)
            li.append(child_ul)

        parent_ul.append(li)


def build_leaf_li(name, filepath, short):
    """
    Build an <li> for a leaf scene (one with no children of its own).
    Leaf scenes are the scenes found in the "root" bucket at any level.

    :param str name: display name of the scene
    :param Path filepath: absolute path to the source .docx file
    :param bool short: show only the filename, not the full path
    :returns: BeautifulSoup Tag (<li class="tree-node leaf-scene">)
    """
    li = SOUP.new_tag("li")
    li["class"] = ["tree-node", "leaf-scene"]

    content_div = SOUP.new_tag("div")
    content_div["class"] = "node-content"

    # Twistie (hidden via CSS for leaf nodes, but keeps alignment)
    twistie = SOUP.new_tag("span")
    twistie["class"] = "twistie"
    content_div.append(twistie)

    # Icon
    icon_span = SOUP.new_tag("span")
    icon_span["class"] = "icon"
    content_div.append(icon_span)

    # Name
    name_span = SOUP.new_tag("span")
    name_span["class"] = "name"
    name_span.string = name
    content_div.append(name_span)

    # Source link
    display_path = Path(filepath).name if short else str(filepath)
    file_uri = "file:///" + str(filepath)
    link = SOUP.new_tag("a", href=file_uri)
    link["class"] = "source-link"
    link["target"] = "_blank"
    link.string = display_path
    content_div.append(link)

    li.append(content_div)
    return li


def _node_has_visible_children(children_dict):
    """
    Return True if the children dict contains anything that should
    be rendered as child nodes (i.e., any keys beyond an empty or
    non-existent "root" list, or a "root" list that actually has items).
    """
    if not children_dict:
        return False
    for key, val in children_dict.items():
        if key == "root":
            if val:  # non-empty root list
                return True
        else:
            return True  # named sub-node exists
    return False


def _build_node_classes(node_type, has_children, expandable=True, is_root=False):
    """
    Build the list of CSS classes for a tree-node <li>.

    :param int node_type: 1 = folder, 2 = scene
    :param bool has_children: whether the node contains sub-items
    :param bool expandable: whether the node should be collapsible
        via Expand All / Collapse All and click-to-toggle. Nodes
        with children but expandable=False (e.g. the root) still
        get .has-children but omit .expandable and the twistie.
    :param bool is_root: whether the node is the tree root
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
    return classes


def project_mapping_HTML(
    tree, proj_name, short, assets_src, output, force, force_assets, nuclear, tree_icons
):
    """
    Creates HTML file with the scene <-> src file
    mapping for a SmartEdit Writer project, and writes
    it in this script dir

    :param dict tree: the mapping of scenes/src files,
        and their heirarchy in the project (what's generated
        by sequential calls to scene_tree / insert within
        db_info)
    :paran str proj_name: name of the project
    :param bool short: only display filenames of the src
        files rather than entire abs paths
    :param Path assets_src: Path where source assets/ lives.
    :param Path output: path to write file to
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
    """
    soup = beautiful_soup_utils.make_soup_from_file(TEMPLATE, False)

    # select a random icon for the tree root
    random_index = random.randint(0, len(tree_icons) - 1)
    tree_root_icon = tree_icons[random_index]

    tree_soup = make_tree(tree, proj_name, short, tree_root_icon)
    beautiful_soup_utils.find_replace_str(soup, "%TREE%", tree_soup)
    beautiful_soup_utils.replace_all(soup, "%PROJECT%", proj_name)

    # Count leaf scenes for the badge
    scene_count = count_leaves(tree)
    beautiful_soup_utils.replace_all(soup, "%COUNT%", str(scene_count))

    # If output file already exists and force not given, error
    if output.exists() and not force:
        raise Exception(
            f"Output already exists: {output}. (Try re-running script with --force)"
        )

    beautiful_soup_utils.write_soup_to_file(
        soup, str(output), force, True, True, [], False
    )

    # copy assets directory to final output
    assets_dest = output.parent / "assets"
    copy_assets_to_output(assets_src, assets_dest, force_assets, nuclear)

    webbrowser.open(str(output))


def count_leaves(tree):
    """
    Count the total number of leaf scenes in the mapping tree.
    A leaf is any scene in a "root" bucket — these are the
    terminal items with source files.

    :param dict tree: the mapping generated by db_info()
    :returns int: total count of leaf scenes
    """
    count = len(tree.get("root", []))
    for key, node_data in tree.items():
        if key == "root":
            continue
        children = node_data.get("children", {})
        if children:
            count += count_leaves(children)
    return count


def print_scene_tree(curr_tree, short, d=0):
    """
    print gathered db info to stdout

    :param dict curr_tree: nested dictionary mapping the scene hierarchy,
        where leaf values are [Path, str] pairs (Path is the .docx file,
        str is the scene name)
    :param bool short: only print the filename, not
        entire filepath
    :param int d: indentation depth (used internally for recursion)
    """

    spacer = "    "
    lspace = spacer * d
    # at root for this level
    if "root" in curr_tree:
        # there's scenes at this level
        # get length of longest scene name in this batch
        scenes = curr_tree["root"]
        max_scene_name = max_length(
            [item[1] for item in scenes]
        )  # list of only the scene names
        for scene_mapping in scenes:
            scene_name = scene_mapping[1]
            source_path = scene_mapping[0]
            if short:
                source_path = Path(source_path).name
            padding = " " * (max_scene_name - len(scene_name))
            print(f"{lspace}{FILE_ICON} {scene_name}{padding} --> {source_path}")
    for key in curr_tree.keys():
        # type of this obj (is it a folder or a scene?)
        if key != "root":
            obj_type = curr_tree[key]["type"]
            icon = FILE_ICON
            if obj_type == 1:
                icon = FOLDER_ICON
            print(f"{lspace}{icon} {key}")
            next_tree = copy.deepcopy(curr_tree[key]["children"])
            print_scene_tree(next_tree, short, d + 1)


def get_name(obj_id, cur):
    """
    Get user defined name of an object in
    a SmartEdit Writer project from its
    id in the sqlite db
    (user defined name = current name in
    the SmartEdit Writer UI; i.e. name of
    a scene, folder, etc.

    :param int obj_id: id of the object in
        sqlite db for the project
    :param Sqlite3.Cursor cur: cursor connected to
        the sqlite db for project, which allows you to
        query the db
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
    Get object type

    :param int obj_id: id of the object in
        sqlite db for the project
    :param Sqlite3.Cursor cur: cursor connected to
        the sqlite db for project, which allows you to
        query the db
    """
    res = list(
        cur.execute("SELECT ItemType FROM Metadata " + "WHERE ID=" + str(obj_id))
    )
    if not res:
        raise Exception(f"can't determine type for id {obj_id}")
    if len(res) > 1:
        raise Exception(f"query in sqlite db returned more than one type for {obj_id}")
    return res[0][0]


def file_from_id(obj_id, doc_path):
    """
    given an id in the sqlite db,
    return the filename for that obj

    :param int obj_id: id of the object in the sqlite db
    :param Path doc_path: absolute path to the Documents directory
        for the SmartEdit Writer project
    :returns Path: path to the .docx file for the given object
    """
    return doc_path / f"{obj_id}.docx"


def get_parent_id(obj_id, cur):
    """
    get the id of parent for an object
    in sqlite db

    :param int obj_id: id of object in project's
        sqlite db
    :param Sqlite3.Cursor cur: cursor connected to
        the sqlite db for project, which allows you to
        query the db
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


def scene_tree(obj_id, cur, curr_scene_tree):
    """
    recursive method to determine tree for a scene:
    i.e. for scene nested in UI as
    folder1 -> folder2 -> myScene
    it starts at the scene, and keeps querying the db
    for parents until it makes it to the root (top of
    project)

    :param int obj_id: id in sqlite db for current object
        being evaluated (i.e. in example above, this func
        would end up being called 3 times: once for myScene,
        then for folder2, then for folder1; obj_id is the
        db id for whichever obj is currently being processed)
    :param Sqlite3.Cursor cur: cursor connected to
        the sqlite db for project, which allows you to
        query the db
    :param list[[list[str, str, str]] curr_scene_tree:
        list that's been found up to this point; a list of
        lists, where each inner list has data for each position/
        object in the heiracrhy (see :return: for more example)

    :return list[[list[str, str, str]]
        list of lists. each inner list has info for an
        object in the heirarchy for this scene which includes
        1. the UI name (i.e. a folder name, a scene name)
        2. object type (ItemType in Metadata table in sqlite db)
        3. object's id in the sqlite db
        so for example, if there's a scene at:
        folder1 -> folder2 -> myScene, what ultikmately will be
        returned is a list:
        [[folder1, 1, x], [folder2, 1, y], [myScene, 2, z]]
        (where x, y, and z are the ids for these obj in the db)
        - this is a recursive function, so what's being returned
        is the curr list for heiracrhy found so far
    """

    # get parent for this object (i.e. a chapter folder)
    parent_id = get_parent_id(obj_id, cur)
    if not parent_id:
        # base case: no parent -- at root level
        return list(reversed(curr_scene_tree))
    # get user name for the parent
    parent_user_name = get_name(parent_id, cur)
    parent_type = get_type(parent_id, cur)
    curr_scene_tree.append([parent_user_name, parent_type, parent_id])
    return scene_tree(parent_id, cur, curr_scene_tree)


def insert(organized, parent_list, mapping, doc_path):
    """
    insert a new branch on the scene tree into the
    mapping of scenes/src files

    :param dict organized: the dict to insert the new branch into
    :param list parent_list: list of [str, int, int] where the elements are
        (UI display name, ItemType from Metadata table, database ID)
        for each level in the hierarchy from root to leaf
    :param list mapping: [Path, str] where Path is the .docx file
        path and str is the scene name
    :param Path doc_path: absolute path to the Documents directory
    """
    curr_hash = organized
    for idx, parent_info in enumerate(parent_list):
        parent_name = parent_info[0]
        parent_type = parent_info[1]
        parent_id = parent_info[2]
        filename = None
        if parent_type == 2:
            # its another scene
            filename = file_from_id(parent_id, doc_path)
        if parent_name not in curr_hash:
            curr_hash[parent_name] = {
                "type": parent_type,
                "source": filename,
                "children": {},
            }
        if (
            idx == len(parent_list) - 1
            and "root" not in curr_hash[parent_name]["children"]
        ):
            curr_hash[parent_name]["children"]["root"] = []
        curr_hash = curr_hash[parent_name]["children"]
    curr_hash["root"].append(mapping)


def db_info(proj_path):
    """
    Determine paths to source files for all scenes in a
    SmartEdit Writer project from its sqlite database;
    collect that info into an organized hash.

    :param Path proj_path: absolute path to a SmartEdit Writer project
        directory (the parent of .atomic and Documents)
    :returns dict: nested dictionary mapping the scene hierarchy to
        source file paths. Leaves contain lists of [Path, str] where
        Path is the absolute path to the .docx source file and str
        is the scene name as displayed in the UI.
    """

    db_path = proj_path / ".atomic" / "atomic.meta"  # project db
    doc_path = proj_path / "Documents"  # dir with src files

    con = sqlite3.connect(str(db_path))
    cur = con.cursor()

    # cur.execute("SELECT name FROM sqlite_master WHERE type='table';")
    # print(cur.fetchall())

    """
    table "Metadata" contains scene data:
        id: db id (filename based on this)
        UserDefinedName: name of scene within the UI
    """

    res = list(
        cur.execute(
            "SELECT id, UserDefinedName FROM Metadata WHERE "
            + "ItemType=2 AND section=1"
        )
    )

    # organize by sections
    organized = {}
    for results in res:
        scene_id = results[0]
        scene_name = results[1]
        filename = file_from_id(scene_id, doc_path)

        mapping = [filename, scene_name]

        # parent hierarchy for scene
        scene_tree_list = scene_tree(scene_id, cur, [])

        # insert by going through each parent
        insert(organized, scene_tree_list, mapping, doc_path)

    cur.close()
    con.close()

    return organized


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
# GENERAL UTILITY FUNCTIONS
# ============================================================================


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
        "-r",
        "--remove",
        required=False,
        default=False,
        action="store_true",
        help="don't print project name",
    )
    parser.add_argument(
        "--html",
        required=False,
        default=False,
        action="store_true",
        help="make HTML file (else prints to console)",
    )
    parser.add_argument(
        "--output",
        required=False,
        type=Path,
        help=f"Output path for HTML file. Must supply --html.",
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
        "--nuclear",
        action="store_true",
        help="USE AT YOUR OWN RISK. Force delete existing assets/ dir by removing "
        "read-only permissions. Only use if --force-assets fails with 'Access denied'.",
    )
    args = parser.parse_args(args)

    # Validate --project
    if args.project and not args.project.exists():
        raise Exception(f"--project doesn't exist ({args.project})")
    if args.project and not args.project.is_dir():
        raise Exception(f"--project isn't a directory ({args.project})")

    # Validate --search-root
    if not args.search_root.exists():
        raise Exception(f"--search-root doesn't exist ({args.search_root})")
    if not args.search_root.is_dir():
        raise Exception(f"--search-root isn't a directory ({args.search_root})")
    search_root = args.search_root.resolve()

    # Validate --output
    if args.output and args.output.is_dir():
        # --output is an existing dir (Path.is_dir() returns False if Path doesn't exist)
        raise Exception(f"--output is a directory, not a file ({args.output})")
    if args.output and not args.html:
        raise Exception(f"--html required for --output")
    # resolve in case --output a rel path.
    # Note: stict=False required or will fail if path doesn't yet exist
    html_report_path = (args.output or DEFAULT_HTML_REPORT_PATH).resolve(strict=False)

    # if --project not given, will scan all projects in search_root
    # and prompt user to continuously select one until they select
    # option 0 (exit criteria). Get their initial selection.
    proj_path = args.project
    projects = []
    if not proj_path:
        projects, proj_path = get_project_interactively(
            search_root, not args.norecursive
        )

    # Resolve to handle symlinks, rel paths.
    proj_path = proj_path.resolve()

    # Continue prompting user to select a project unless:
    # 1. they select option 0 (exits in chose_project)
    # 2. --project was given (exits after first iteration)
    # 3. --html was given (exits after first iteration)
    while True:
        proj_name = proj_path.name
        scene_mapping = db_info(proj_path)
        # remove the project name from the scene mapping
        if args.remove:
            if len(scene_mapping.keys()) > 1:
                raise Exception("can't remove project name due to multiple keys")
            key = list(scene_mapping.keys())[0]
            scene_mapping = scene_mapping[key]["children"]
        if args.html:
            project_mapping_HTML(
                scene_mapping,
                proj_name,
                True,
                ASSETS_SRC,
                html_report_path,
                args.force,
                args.force_assets,
                args.nuclear,
                TREE_ROOT_ICON_CLASSES,
            )
        else:
            print_scenes(scene_mapping, proj_name, args.short)

        if args.project or args.html:  # --project given, don't ask again
            sys.exit(0)

        # ask user to select another project
        proj_path = chose_project(projects)


if __name__ == "__main__":
    args = sys.argv[1:]
    main(args)
