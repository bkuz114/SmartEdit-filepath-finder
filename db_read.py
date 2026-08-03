"""
Finds the source files for scenes in a SmartEdit Writer project
and displays them either on stdout or in an HTML file.

Usage:
    python db_read.py [--project PROJECT] [--short] [--remove] [--html]

    --project PROJECT:
        abs path to a SmartEdit Writer Project
        if not given, finds all projects
        and asks you to select one
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

SCRIPT_DIR = os.path.dirname(os.path.realpath(__file__))  # path of py script
sys.path.insert(1, os.path.abspath(os.path.join(SCRIPT_DIR, "libs")))

import io_utils
import beautiful_soup_utils

TEMPLATE = os.path.abspath(os.path.join(SCRIPT_DIR, "template.html"))
SOUP = BeautifulSoup("", "html.parser")

# if user doesn't supply --project, will find
# all SmartEdit Writer projects on the machine;
# this variabel is where to start the search
SEARCH_ROOT = "C:\\Users\\Boris\\Documents"
FILE_ICON = "-"  # for displaying scene tree on stdout
FOLDER_ICON = "+"  # ""


def find_projects():
    """
    find all SmartEdit Writer projects
    on the file system

    :returns lst[str]: list of abs paths
        to SmartEdit Writer projects found
    """
    result = []
    for root, dirs, files in os.walk(SEARCH_ROOT):
        if "atomic.scribbler" in files:
            proj_path = os.path.join(SEARCH_ROOT, root)
            result.append(proj_path)
    return result


def chose_project(projects):
    """
    displays a numbered list of SmartEdit Writer projects
    and prompts user to select one, then returns selected
    project

    :param lst[str]: list of abs filepaths to SmartEdit Writer
        projects to display to the user.
    :returns str: abs path to the selected SmartEdit Writer project
    """
    for idx, project in enumerate(projects):
        print("[" + str(idx + 1) + "] : " + project)
    num = int(input("\nPlease select project number (enter 0 to exit): "))
    if num == 0:
        sys.exit(0)
    return projects[num - 1]


def get_project_interactively():
    """
    Finds all SmartEdit Writer projects on the file
    system and prompts user to select one.

    :returns lst[str], str:
        lst[str]: is the list o abs paths of all SmartEdit Writer
            projects found on the system.
        str is the abs path to the project selected
            by the user
    """
    print("\nfinding SmartEdit Writer projects...\n", flush=True)
    projects = find_projects()
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
        "-p", "--project", required=False, help="SmartEdit Project Directory"
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

    proj_path = args.project
    projects = []
    if not proj_path:
        projects, proj_path = get_project_interactively()

    while True:
        if not os.path.exists(proj_path):
            raise Exception("\n--path doesn't exist (" + proj_path + ")")
        if not os.path.isabs(proj_path):
            raise Exception("\n--path isn't absolute (" + proj_path + ")")
        if not os.path.isdir(proj_path):
            raise Exception("\n--path isn't a directory (" + proj_path + ")")

        proj_name = os.path.basename(proj_path)
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

        if args.project or args.html:  # --project given, don't interactive
            sys.exit(0)
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


def make_table(tree, proj_name, short):
    """
    creates HTML for a <table> containing
    the mapping of scenes and their src files

    :param dict tree: dict containing the mapping,
        as is generated by
    :param str proj_name: name of the project
    :param bool short: only display the filename
        of projects' src files, rather than their
        entire abs path
    """
    table_soup = SOUP.new_tag("table")
    make_table_recursive(table_soup, tree, 1, short)
    return table_soup


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
    table_soup = make_table(tree, proj_name, short)
    beautiful_soup_utils.find_replace_str(soup, "%TABLE%", table_soup)
    beautiful_soup_utils.replace_all(soup, "%PROJECT%", proj_name)

    output = os.path.join(SCRIPT_DIR, "table.html")
    beautiful_soup_utils.write_soup_to_file(soup, output, True, True, True, [], False)

    webbrowser.open(output)


def new_row(name, mapping, obj_type, colnum, short):
    """
    creates new <tr> for HTML table for scene/src file mapping.
    specifically, the table prints the entire tree for the
    project (i.e. Folder1 -> Folder2 -> myScene), and each
    position on the tree has its own row to easily format
    things; this function is for printing a row for a single
    position on the tree - e.g. a single folder in a heirarchy,
    or a scene + src file)

    :param str name: name of object (i.e. a scene, a
        folder), within SmartEdit Writer UI that this
        row is for
    :param str mapping: the src file for the object (None
        if there isn't one -- e.g. if the object is a folder)
    :param int obj_type: type of the object ('ItemType'
        attr in the MetaData table for the project's sqlite db)
    :param int colnum:
        the col position to print the object (folder, scene)
        in
    :param bool short:
        if will be printing info on a src file in this row,
        only display the filename, not the entire abs path
    """
    css_cls = "file"
    if obj_type == 1:
        css_cls = "folder"
    row = SOUP.new_tag("tr")
    for i in range(colnum - 1):
        row.append(SOUP.new_tag("td"))

    data_cell = SOUP.new_tag("td")
    data_cell.string = name
    beautiful_soup_utils.add_classes(data_cell, [css_cls])
    row.append(data_cell)
    if mapping:
        displaypath = mapping
        if short:
            displaypath = os.path.basename(mapping)
        filemap = "file:///" + mapping
        new_td = '<td><a href="{}" target="_blank">{}</a></td>'.format(
            filemap, displaypath
        )
        data_cell2 = BeautifulSoup(new_td, "html.parser")
        row.append(data_cell2)
    return row


def make_table_recursive(table, curr_tree, col, short):
    """
    recursive method for generating the HTML table
    for scene / src file mapping

    :param BeautifulSoup4 tag table: a <table> tag for
        the table being built
    :param dict curr_tree: current subtree to make table for
        (the original tree is what is being built up by
        sequential calls to scene_tree / insert)
    :param bool short: for scenes (leaves on the tree),
        only display the filenames of the src files (not
        entire abs path)

    :return None: the table object is modified permenantly
        with each call to make_table_recursive, thus building
        it up
    """

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
            # add to table
            row = new_row(scene_name, source_path, 2, col, short)
            table.append(row)

    for key in curr_tree.keys():
        if key != "root":
            obj_type = curr_tree[key]["type"]
            obj_src = curr_tree[key]["source"]
            # add to table
            row = new_row(key, obj_src, obj_type, col, short)
            table.append(row)
            next_tree = copy.deepcopy(curr_tree[key]["children"])
            make_table_recursive(table, next_tree, col + 1, short)


def print_scene_tree(curr_tree, short, d=0):
    """
    print gathered db info to stdout

    :param hash organized: hash with filepath mapping
    :param bool short: only print the filename, not
        entire filepath
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
                source_path = os.path.basename(source_path)
            padding = " " * (max_scene_name - len(scene_name))
            print(
                lspace + FILE_ICON + " " + scene_name + padding + " --> " + source_path
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
    """
    return os.path.join(doc_path, str(obj_id) + ".docx")


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

    :param dict organized: the dict to insert the
        new branch into
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

    :param str db_path: absolute path to the sqlite db
        for a SmartEdit Writer project
    :param str doc_path: absolute path to the document
        directory for the SmartEdit Writer project, where
        all source files are contained.
    """

    db_path = os.path.join(proj_path, ".atomic\\atomic.meta")  # project db
    doc_path = os.path.join(proj_path, "Documents")  # dir with src files

    con = sqlite3.connect(db_path)
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
