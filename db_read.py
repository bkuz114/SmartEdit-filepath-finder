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
import argparse
import webbrowser
import sqlite3
import copy
from bs4 import BeautifulSoup
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent  # path of py script
sys.path.insert(1, str(SCRIPT_DIR / "libs"))

import io_utils
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
        print("[" + str(idx + 1) + "] : " + str(project))
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
    args = parser.parse_args(args)

    # Validate --search-root
    if not args.search_root.is_dir():
        raise Exception(
            "\n--search-root isn't a directory (" + str(args.search_root) + ")"
        )
    search_root = args.search_root.resolve()

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
    # strict = False to avoid FileNotFound if path doesn't exist
    proj_path = Path(proj_path).resolve(strict=False)
    if not proj_path.exists():
        raise Exception("\nproject doesn't exist (" + str(proj_path) + ")")
    if not proj_path.is_absolute():
        raise Exception("\nproject isn't absolute (" + str(proj_path) + ")")
    if not proj_path.is_dir():
        raise Exception("\nproject isn't a directory (" + str(proj_path) + ")")

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
            project_mapping_HTML(scene_mapping, proj_name, True)
        else:
            print_scenes(scene_mapping, proj_name, args.short)

        if args.project or args.html:  # --project given, don't ask again
            sys.exit(0)

        # ask user to select another project
        proj_path = chose_project(projects)


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
    print("    " + proj_name + ":\n")
    print_scene_tree(curr_tree, short, d=0)
    print("===========================\n")


def make_tree(tree, proj_name, short):
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
    :returns: BeautifulSoup Tag (a <ul class="tree"> element)
    """
    root_ul = SOUP.new_tag("ul")
    root_ul["class"] = "tree"
    make_tree_recursive(root_ul, tree, short, False)
    return root_ul


def make_tree_recursive(parent_ul, curr_tree, short, expandable=True):
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

        li = SOUP.new_tag("li")
        li["class"] = _build_node_classes(node_type, has_children, expandable)

        # --- Build the visible row ---
        content_div = SOUP.new_tag("div")
        content_div["class"] = "node-content"

        # Twistie arrow (only meaningful if the node has children)
        # (actual arrow controlled via CSS ::before)
        if expandable:
            twistie = SOUP.new_tag("span")
            twistie["class"] = "twistie"
            # twistie.string = "▶"
            content_div.append(twistie)

        # Icon
        icon_span = SOUP.new_tag("span")
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
            make_tree_recursive(child_ul, children, short)
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


def _build_node_classes(node_type, has_children, expandable=True):
    """
    Build the list of CSS classes for a tree-node <li>.

    :param int node_type: 1 = folder, 2 = scene
    :param bool has_children: whether the node contains sub-items
    :param bool expandable: whether the node should be collapsible
        via Expand All / Collapse All and click-to-toggle. Nodes
        with children but expandable=False (e.g. the root) still
        get .has-children but omit .expandable and the twistie.
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
    return classes


def project_mapping_HTML(tree, proj_name, short):
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
    """
    soup = beautiful_soup_utils.make_soup_from_file(TEMPLATE, False)
    tree_soup = make_tree(tree, proj_name, short)
    beautiful_soup_utils.find_replace_str(soup, "%TREE%", tree_soup)
    beautiful_soup_utils.replace_all(soup, "%PROJECT%", proj_name)

    # Count leaf scenes for the badge
    scene_count = count_leaves(tree)
    beautiful_soup_utils.replace_all(soup, "%COUNT%", str(scene_count))

    output = SCRIPT_DIR / "report.html"
    beautiful_soup_utils.write_soup_to_file(
        soup, str(output), True, True, True, [], False
    )

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
            print(
                lspace
                + FILE_ICON
                + " "
                + scene_name
                + padding
                + " --> "
                + str(source_path)
            )
    for key in curr_tree.keys():
        # type of this obj (is it a folder or a scene?)
        if key != "root":
            obj_type = curr_tree[key]["type"]
            icon = FILE_ICON
            if obj_type == 1:
                icon = FOLDER_ICON
            print(lspace + icon + " " + key)
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
        raise Exception("can't determine user defined name for id " + str(obj_id))
    if len(res) > 1:
        raise Exception(
            "query in sqlite db returned more than one " + "name for " + str(obj_id)
        )
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
        raise Exception("can't determine type for id " + str(obj_id))
    if len(res) > 1:
        raise Exception(
            "query in sqlite db returned more than one " + "type for " + str(obj_id)
        )
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
        raise Exception("found more than one parent for scene " + str(obj_id) + "!")
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


if __name__ == "__main__":
    args = sys.argv[1:]
    main(args)
