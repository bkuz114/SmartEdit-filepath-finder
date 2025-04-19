"""
Prints the filepaths for Scenes in a SmartEdit Writer project.

Usage:
    python db_read.py [--project PROJECT] [--short] [--remove]

    --project PROJECT:
        abs path to a SmartEdit Writer Project
        if not given will find all projects
        and ask user to select one
    --short:
        print only the filename of scene (not its abs path)
    --remove:
        don't display project name
"""

import sys
import os
import argparse
import webbrowser
import sqlite3
import copy
from bs4 import BeautifulSoup

SCRIPT_DIR = os.path.dirname(os.path.realpath(__file__))  # path of py script
sys.path.insert(1, os.path.abspath(os.path.join(SCRIPT_DIR, 'libs')))

import io_utils
import beautiful_soup_utils

TEMPLATE = os.path.abspath(os.path.join(SCRIPT_DIR, "template.html"))
SOUP = BeautifulSoup("", 'html.parser')

DB_DIR = ".atomic\\atomic.meta"
DOC_DIR = "Documents"

SEARCH_ROOT = "C:\\Users\\Boris\\Documents"
FILE_ICON = "-"
FOLDER_ICON = "+"


def find_projects():
    result = []
    for root, dirs, files in os.walk(SEARCH_ROOT):
        if "atomic.scribbler" in files:
            proj_path = os.path.join(SEARCH_ROOT, root)
            result.append(proj_path)
    return result


def chose_project(projects):
    for idx, project in enumerate(projects):
        print("[" + str(idx + 1) + "] : " + project)
    num = int(input("\nPlease select project number (enter 0 to exit): "))
    if num == 0:
        sys.exit(0)
    return projects[num-1]


def get_project_interactively():
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
        description='Print db data for SmartEdit Writers',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument('-p', '--project',
                        required=False,
                        help='SmartEdit Project Directory')
    parser.add_argument('-s', '--short',
                        required=False,
                        default=False,
                        action="store_true",
                        help='print filenames only, not complete paths')
    parser.add_argument('-r', '--remove',
                        required=False,
                        default=False,
                        action="store_true",
                        help="don't print project name")
    parser.add_argument('--html',
                        required=False,
                        default=False,
                        action="store_true",
                        help="make HTML file (else prints to console)")
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
            mapping_page(scene_mapping, proj_name, True)
        else:
            print_scenes(scene_mapping, proj_name, args.short)

        if args.project or args.html: # --project given, don't interactive
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


def create_table(tree, proj_name, short):
    table_soup = SOUP.new_tag("table")
    make_table(table_soup, tree, 1, short)
    return table_soup


def mapping_page(tree, proj_name, short):
    soup = beautiful_soup_utils.make_soup_from_file(TEMPLATE, False)
    table_soup = create_table(tree, proj_name, short)
    beautiful_soup_utils.find_replace_str(soup, "%TABLE%", table_soup)
    beautiful_soup_utils.replace_all(soup, "%PROJECT%", proj_name)

    output = os.path.join(SCRIPT_DIR, "table.html")
    beautiful_soup_utils.write_soup_to_file(soup, output, True, True, True, [], False)

    webbrowser.open(output)


def new_row(name, mapping, obj_type, colnum, short):

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
        new_td = '<td><a href="{}" target="_blank">{}</a></td>'.format(filemap, displaypath)
        data_cell2 = BeautifulSoup(new_td, 'html.parser')
        row.append(data_cell2)
    return row


def make_table(table, curr_tree, col, short):
    """
    create an HTML table
    from scene mapping tree
    """

    if "root" in curr_tree:
        # there's scenes at this level
        # get length of longest scene name in this batch
        scenes = curr_tree["root"]
        max_scene_name = max_length([item[1] for item in scenes])  # list of only the scene names
        for scene_mapping in scenes:
            scene_name = scene_mapping[1]
            source_path = scene_mapping[0]
            # add to table
            row = new_row(scene_name, source_path, 2, col, short)
            table.append(row)

    for key in curr_tree.keys():
        if key != "root":
            obj_type = curr_tree[key]['type']
            obj_src = curr_tree[key]['source']
            # add to table
            row = new_row(key, obj_src, obj_type, col, short)
            table.append(row)
            next_tree = copy.deepcopy(curr_tree[key]["children"])
            make_table(table, next_tree, col+1, short)


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
        max_scene_name = max_length([item[1] for item in scenes])  # list of only the scene names
        for scene_mapping in scenes:
            scene_name = scene_mapping[1]
            source_path = scene_mapping[0]
            if short:
                source_path = os.path.basename(source_path)
            padding = " " * (max_scene_name - len(scene_name))
            print(lspace + FILE_ICON + " " + scene_name + padding +
                  " --> " + source_path)
    for key in curr_tree.keys():
        # type of this obj (is it a folder or a scene?)
        if key != "root":
            obj_type = curr_tree[key]['type']
            icon = FILE_ICON
            if obj_type == 1:
                icon = FOLDER_ICON
            print(lspace + icon + " " + key)
            next_tree = copy.deepcopy(curr_tree[key]["children"])
            print_scene_tree(next_tree, short, d+1)


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
    :param cur: cursor for sqlite connection
    """
    res = list(cur.execute("SELECT UserDefinedName FROM Metadata " +
                           "WHERE ID=" + str(obj_id)))
    if not res:
        raise Exception("can't determine user defined name for id " +
                        str(obj_id))
    if len(res) > 1:
        raise Exception("query in sqlite db returned more than one " +
                        "name for " + str(obj_id))
    return res[0][0]


def get_type(obj_id, cur):
    """
    Get object type

    :param int obj_id: id of the object in
        sqlite db for the project
    :param cur: cursor for sqlite connection
    """
    res = list(cur.execute("SELECT ItemType FROM Metadata " +
                           "WHERE ID=" + str(obj_id)))
    if not res:
        raise Exception("can't determine type for id " +
                        str(obj_id))
    if len(res) > 1:
        raise Exception("query in sqlite db returned more than one " +
                        "type for " + str(obj_id))
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
    :param cur: cursor for sqlite connection for
        project
    """
    res = list(cur.execute("SELECT ParentId FROM DisplayTrees " +
                           "WHERE ItemId=" + str(obj_id)))
    if not res:
        # no parent -- root level
        return None
    if len(res) > 1:
        raise Exception("found more than one parent for scene " +
                        str(obj_id) + "!")
    return res[0][0]


def scene_tree(obj_id, cur, curr_scene_tree):
    """
    determine the tree for a scene:
    i.e. its parent folders
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
            curr_hash[parent_name] = {"type": parent_type,
                                      "source": filename,
                                      "children": {}}
        if idx == len(parent_list) - 1 and "root" not in curr_hash[parent_name]["children"]:
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

    db_path = os.path.join(proj_path, DB_DIR)
    doc_path = os.path.join(proj_path, DOC_DIR)

    con = sqlite3.connect(db_path)
    cur = con.cursor()

    #cur.execute("SELECT name FROM sqlite_master WHERE type='table';")
    #print(cur.fetchall())

    """
    table "Metadata" contains scene data:
        id: db id (filename based on this)
        UserDefinedName: name of scene within the UI
    """

    res = list(cur.execute("SELECT id, UserDefinedName FROM Metadata WHERE " +
                           "ItemType=2 AND section=1"))

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
