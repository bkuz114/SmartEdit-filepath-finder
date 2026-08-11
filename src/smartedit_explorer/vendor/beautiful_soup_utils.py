"""
Some useful utilities for using BeautiulSoup4 to
manupulate HTML docs.
"""

import os
import copy
import re
from pathlib import Path
import bs4  # needed to typecheck objects i.e. bs4.element.Tag
from bs4.dammit import EntitySubstitution  # for custom formatter for prettify
from bs4 import BeautifulSoup, Comment

ENC = "utf-8-sig"

FILENAME = os.path.basename(__file__)
# common str to prefix to HTML comments being added by this lib
# needed so that there's a way to remove all HTML comments
# except internal ones
COMMENT_PREFIX = " " + FILENAME + " "
# define internal link + script tag comments
# here (rather than in individual functions)
# so that they can be imported in unit tests
LINK_COMMENT_SUFFIX = "added this link tag"
SCRIPT_COMMENT_SUFFIX = "added this script tag"
LINK_COMMENT = COMMENT_PREFIX + LINK_COMMENT_SUFFIX
SCRIPT_COMMENT = COMMENT_PREFIX + SCRIPT_COMMENT_SUFFIX


def read_file(filepath: Path) -> str:
    """
    Reads and validates an input file and returns raw content.

    Args:
        filepath: Path to file.

    Returns:
        Raw text of file.

    Raises:
        FileNotFoundError: If filepath doesn't exist.
    """
    if not filepath.exists():
        raise FileNotFoundError(f"Input file not found: {filepath}")

    with open(filepath, "r", encoding="utf-8") as f:
        return f.read()


def write_file(content: str, filepath: Path, force: bool = False) -> None:
    """
    Write a file to disk, checking for existing file and force flag.

    Args:
        content: Content to write.
        filepath: Path to write file to. Creates parent dirs if they don't exist.
        force: Whether to overwrite existing file.

    Raises:
        FileExistsError: If file exists and force is False.
    """
    if filepath.exists() and not force:
        raise FileExistsError(f"{filepath} already exists. Use force to overwrite.")

    filepath.parent.mkdir(parents=True, exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)


def ensure_html_document(soup):
    """
    Ensure a BeautifulSoup object has a complete HTML document
    structure: <html>, <head>, and <body>.

    Modifies the soup object in place. If any of these elements are
    missing, they are created and existing content is moved into
    <body>. This is useful for wrapping HTML fragments (e.g. mammoth
    converter output) into a valid, self-contained document that can
    accept a stylesheet link or other <head> content.

    :param soup: BeautifulSoup object to normalize
    """
    # Ensure <html> exists
    if not soup.html:
        html_tag = soup.new_tag("html")
        # Move any existing top-level content (text nodes, fragments)
        # into the new <html> before proceeding
        for child in list(soup.children):
            child.extract()
            html_tag.append(child)
        soup.append(html_tag)
    else:
        html_tag = soup.html

    # Ensure <head> exists
    if not html_tag.head:
        head_tag = soup.new_tag("head")
        html_tag.insert(0, head_tag)

    # Ensure <body> exists
    if not html_tag.body:
        body_tag = soup.new_tag("body")
        # Move all content that isn't <head> into <body>
        for child in list(html_tag.children):
            if child is not html_tag.head:
                child.extract()
                body_tag.append(child)
        html_tag.append(body_tag)


def encapsulate_tag_text(
    soup, tag_search, tag_search_attrs, tag_add, tag_add_attrs, use_nbsp=False
):
    """
    Encapsulate plain strings within a tag within another tag.

    :param BeautifulSoup4 soup: beautifulsoup4 object to modify
    :param String tag_search: name of tag to search for within soup
    :param dict<String> tag_search_attrs: dictionary of HTML attrs
        for the tag to search (e.g. {"class": "a", "lang": "ru"})
    :param string tag_add: name of tag to encapsulate any plain
        strings that are found within the retrieved tags
    :param dict<String> tag_add_attrs: dictionary of HTML attrs
        for the encapsulating tag
    :pararm boolean use_nbsp: if True, then after encapsulating
        each plain string, will modify that string such that
        it's last and first char -- if a whitespace -- will be replaced
        with &nbsp; (this is needed for declension/ repo, as the
        font-size of many <p> tags is 0 to remove default padding
        around child <span>s; but this means all strings within
        those <p> tags must be in tags themselves (else they won't
        show up, as they will have font-size=0), and furthermore,
        those whitespace chars surrounding <span>s won't render,
        unless you make them &nbsp; chars

    example:

    Suppose you want to find all <p class="a"> in a soup, and then
    encapsulate any plain strings in it in <span class="b">

    encapsulate_tag_text(soup, "p", {"class": "a"}, "span", {"class": "b"})

    <p class="a">
        Here is <span class="b">text</span> !
    </p>
    becomes
    <p class="a">
        <span class="b">Here is </span>
        <span class="b">text</span><span> !</span>
    </p>
    """
    results = soup.find_all(tag_search, tag_search_attrs)
    for result in results:
        # get all children in the tag - this will include plain strings
        for child in result.children:
            if isinstance(child, bs4.element.NavigableString):
                # encapsulate the string in tag
                # (wrap in versions 4.0.5+)
                child.wrap(soup.new_tag(tag_add, attrs=tag_add_attrs))
                # pad with &nbsp; if requested
                if use_nbsp:
                    plain_str = child.string
                    if plain_str.endswith(" "):
                        plain_str = plain_str[:-1] + "\xa0"  # \x0 is &nbsp;
                    if plain_str.startswith(" "):
                        plain_str = "\xa0" + plain_str[1:]
                    child.string.replace_with(plain_str)


def has_text_content(tag):
    """
    check if a BeautifulSoup tag has text.

    :return: True if tag has text, False otherwise

    (@TODO: Ensure this is a Tag object?)
    https://stackoverflow.com/questions/61794102/how-to-remove-empty-p-tags-with-beautiful-soup-4
    """
    if len(tag.get_text(strip=True)) == 0:
        return False
    return True


def get_next_tag_sibling(soup_tag):
    """
    Returns nearset right sibling that is a Tag object
    (NOT a NavigableString object)
    If right siblings exhausted before it reaches
    a Tag, returns None

    Needed because for things like:

    <p>
      <br/>
      <hr class="inner anchor" id="inner-hr-1"/>
      <br/>
    </p>

    The left and right siblings of the <hr> Tag are
    actually \n chars that are NavigableStrings, not
    the <br> tags, as one might expect...
    """

    curr_tag = soup_tag
    next_sib = None
    while True:
        next_sib = curr_tag.next_sibling
        if isinstance(next_sib, bs4.element.Tag) or not next_sib:
            break
        curr_tag = next_sib
    return next_sib


def get_prev_tag_sibling(soup_tag):
    """
    see func doc for get_next_tag_sibling;
    this is reverse
    """
    curr_tag = soup_tag
    prev_sib = None
    while True:
        prev_sib = curr_tag.previous_sibling
        if isinstance(prev_sib, bs4.element.Tag) or not prev_sib:
            break
        curr_tag = prev_sib
    return prev_sib


def get_furthest_prev_comment_sibling(soup_tag):
    """
    search through left siblings of a tag,
    and keep going until you hit a non-Comment.
    returns the last comment found, or None if
    there were no comments before the tag.
    i.e.
        <p>Stuff</p>
        <!-- a comment -->
        <!-- another -->
        <p>Stuff2</p>
    get_prev_comment_sibling for tag of <p>Stuff2</p>
    will return tag for <!-- a comment -->
    """
    curr_tag = soup_tag
    prev_sib = None
    furthest_comment = None
    while True:
        prev_sib = curr_tag.previous_sibling
        if not isinstance(prev_sib, bs4.element.Comment) or not prev_sib:
            break
        curr_tag = prev_sib
        furthest_comment = prev_sib
    return furthest_comment


def add_classes(tag, class_list):
    """
    add css classes to a BeautifulSoup tag.
    (if a class is already present, won't add it)
    This helper method is useful because a tag's 'class'
    attr can be either a String or a list; handles
    adding in either scenario.

    :param BeautifulSoup4 tag: tag to add classes to
    :param list class_list: css classes to add (as strings)
    :returns: None (Permenantly modifies tag)
    """

    if "class" in tag.attrs:
        """
        BeautifulSoup tag's 'class' attr
        can be str or list
        """
        curr_classes = tag["class"]
        if isinstance(curr_classes, str):
            # dont add dupes
            for new_class in class_list:
                if new_class not in curr_classes:
                    tag["class"] += " " + new_class
        elif isinstance(curr_classes, list):
            # don't add dupes
            final_list = curr_classes
            final_list.extend(x for x in class_list if x not in final_list)
            tag["class"] = final_list
        else:
            # use beautifulsoup4==4.11.1 if you use v 4.13.3 will hit this
            # because the types are different
            raise Exception("Can't identify type of tag's 'class' attr")
    else:
        tag["class"] = class_list


def get_classes(tag):
    """
    Return list of css classes in a BeautifulSoup tag

    :param BeautifulSoup4 tag: soup to get classes from
    :return: the list of css classes in tag (strings)
    """
    classes = []
    if "class" in tag.attrs:
        """
        BeautifulSoup tag's 'class' attr
        could be either String or list
        """
        curr_classes = tag["class"]
        if isinstance(curr_classes, str):
            # split existing class string to get a list
            classes = curr_classes.split(" ")
        elif isinstance(curr_classes, list):
            classes = curr_classes
        else:
            raise Exception(
                "BeautifulSoupUtils: get_classes - class atr"
                " is neither String nor list; can't parse it!"
            )
    return classes


def remove_classes(tag, class_list):
    """
    Remove css classes from a BeautifulSoup tag

    :param BeautifulSoup. element to remove classes from
    :param list class_list: list of strings - the css
        classes to remove. (note: if a class isn't
        found in tag, it's ok)
    :returns: None. modifications to tag are permenant.
    """

    new_class_list = []
    if "class" in tag.attrs:
        """
        BeautifulSoup tag's 'class' attr
        could be either String or list
        """
        curr_classes = tag["class"]
        if isinstance(curr_classes, str):
            # split existing class string to get a list
            curr_classes_list = curr_classes.split(" ")
        elif isinstance(curr_classes, list):
            curr_classes_list = curr_classes
        else:
            raise Exception(
                "BeautifulSoupUtils: remove_classes - class attr "
                "is neither String nor list; can't parse it!"
            )

        for myclass in curr_classes_list:
            if myclass not in class_list:
                new_class_list.append(myclass)
            tag["class"] = new_class_list


def find_replace_str(soup, string, content, allow_empty=False):
    """
    replace first occurance of a string in a BeautifulSoup object
    with other content (either another string, or another beautifulsoup)

    use case:
    html doc with template vars %TITLE% or %MAIN-CONTENT%
    Generate that info elsewhere, then call this to swap it in
      beautiful_soup_utils.find_replace_str(
                    my_soup, "%TITLE%, "my great title")
      beautiful_soup_utils.find_replace_str(
                    my_soup, "%MAIN-CONTENT%", my_soup_div)

    :param BeautifulSoup4 soup: object to replace string in
    :param str string: string to replace
    :param content: what to replace with
    :type content: str or BeautifulSoup4
        (can be <class 'bs4.BeautifulSoup.tag'> or even
        <class 'bs4.BeautifulSoup'>)
    :param bolean allow_empty: optional. if True, don't
        raise Exception if string not found in soup
    :return: True on success, False if didn't find string

    WARNING! ::
    If content is BeauitulfSoup object,
    will convert it to str then back to BeautifulSoup object
    before adding to soup. This could permenantly modify the
    type of attributes in content: example, if you set a boolean
    attribute in content, it will be type String when it's done.
    """

    found = soup.find(string=re.compile(string))
    """
    soup.find with string arg will return a NavigableString
    for the ENTIRE string of the tag that contains the string
    (i.e. suppose you have <h1>%TITLE% %NUMBER%</h1>
    soup.find(string=re.compile("%TITLE%"))
       --> returns "%TITLE% %NUMBER%")
    - if you were to directly replace_with on the find result,
    you'll be replacing the entire text of the tag, not just
    the part of the string that matches. Hence the loginc below:

    1. cast returned NavigableString to string
    2. cast content to replace with to string
    3. use standard string replace on 1.,
       to replace ONLY desired match text
       with 2.
    4. convert result of 3. to BeautifulSoup
    5. Finally, do the replace_with with 4.
    """
    if found:
        found_string = str(copy.copy(found))
        found_replaced = found_string.replace(string, str(content))
        found_replaced = BeautifulSoup(found_replaced, "html.parser")
        found.replace_with(found_replaced)
        return True
    else:
        if allow_empty:
            return False
        else:
            raise Exception("Can't find string {} in soup!".format(string))


def replace_all(soup, string, content):
    """
    replace all occurrances of a string in a bs object
    with something else (another string, or content)

    :param BeautifulSoup4 soup: object to replace string in
    :param str string: string to replace
    :param content: what to replace with
    :type content: str, bs4.BeautifulSoup, or bs4.BeautifulSoup.tag
    :return: None (modified soup permenantly)
    """
    while find_replace_str(soup, string, content, True):
        continue


def js_tag(path):
    """
    returns a <script> tag (as BeautifulSoup object)
    for a path

    :param str path: path to put in the <script> tag
    :return: BeautifulSoup4 object of <script> tag
    """
    # note: <script> tag can not be self-closed like <link> tags
    return BeautifulSoup('<script src="' + path + '"></script>', "html.parser")


def css_tag(path):
    """
    returns a <link> tag (as BeautifulSoup object)
    for a path

    :param str path: path to put in the <link> tag
    :return: BeautifulSoup4 object of <link> tag
    """
    return BeautifulSoup(
        '<link rel="stylesheet" href="'
        + path
        + '" rel="stylesheet" type="text/css" />',
        "html.parser",
    )


def add_js_tags(soup, paths, add_to_head=True):
    """
    add js script tags to soup

    :param BeautifulSoup4 soup: soup to add tags to
    :param list paths: strings of urls to the scripts
        (note: if rel paths, make sure rel the HTML
        doc you're adding to, for where its final
        location will be.
    :param boolean add_to_head: if true, append to <head>,
        else append to <body>

    ** Note - be mindful of js dependencies; if adding
    a scrip that uses jquery, you'd need jquery <script>
    to come before script which relies on it.
    """

    for path in paths:
        script_tag = js_tag(path)
        comment = Comment(SCRIPT_COMMENT)
        script_tag.script.insert_before(comment)
        if add_to_head:
            soup.head.append(script_tag)
        else:
            soup.body.append(script_tag)


def get_css_head_tags(soup):
    """
    return <link> tags in <head>

    :param BeautifulSoup4 soup: soup to get tags from
    :returns: list<bs4.element.Tag> list of link tags
    """
    if not soup.head:
        raise Exception("No <head> tag in soup (can't look for <link> tags)")
    link_tags = soup.head.find_all("link")
    return link_tags


def add_css_head_tags(soup, paths, startAt=None):
    """
    add css tags to <head> of a BeautifulSoup object

    :param BeautifulSoup4 soup: soup to add tags to
    :param list paths: list of Strings, of paths to
        the css files (if giving rel paths, ensure
        they're rel the HTML doc you'd be adding this
        to (where its final location will be)
    :param int startAt: optional. where to start
        inserting the new tags, among existing <link>
        tags in <head>. examples:
            0: adds paths at position 0 (i.e.,
                IN FRONT of all existing tags)
            5: inserts BEFORE the 5th existing tag
        (default behavior is to add after last existing
        <link> tag in <head>)
    :returns: None
    """

    # make list of tags from list of paths
    new_paths = BeautifulSoup("", "html.parser")
    for path in paths:
        link_tag = css_tag(path)
        comment = Comment(LINK_COMMENT)
        link_tag.link.insert_before(comment)
        new_paths.append(link_tag)

    # find last <link> tag in <head> and insert the new
    # paths after that; if there aren't any <link> tags
    # in <head>, append the new paths to end of <head>

    link_tags = get_css_head_tags(soup)
    if not link_tags:
        soup.head.append(new_paths)
    else:
        # default is insert after last <link> tag;
        # but if startAt arg given, insert after that point
        if (
            startAt is not None
        ):  # 0 is valid so don't do if startAt or it won't catch if it's 0
            if not 0 <= startAt <= len(link_tags):
                raise Exception(
                    "\nadd_css_head_tags: specified to start "
                    "adding your new tags at pos {} of existing "
                    "<link> tags, but there are only {} <link> "
                    "tags in this soup's <head>. You must specify "
                    "a number between 0 and {} (inclusive). (p.s. "
                    "if you give {}, that would insert them at the"
                    " end of the list of existing <link> tags, but"
                    " this is the default behavior without the "
                    "startAt args)".format(
                        str(startAt),
                        str(len(link_tags)),
                        str(len(link_tags)),
                        str(len(link_tags)),
                    )
                )
            if startAt == len(link_tags):  # add after last <link>
                link_tags[-1].insert_after(new_paths)
            else:  # anything else, start at that position.
                # be mindful of comments for <link> tags;
                # when inserting before a <link> tag, find
                # comments prior to it and insert before those
                # comments, NOT just before the <link> itself.
                # e.g.: suppose startAt=1, 3 existing <link> tags,
                # and all 3 have HTML comments preceeding;
                # if you were to do: link_tags[1].insertBefore,
                # will end up with:
                #   - comment for link_tag[1]
                #   - new tags
                #   - link_tag[1]
                furthest_comment = get_furthest_prev_comment_sibling(link_tags[startAt])
                if not furthest_comment:  # no comments preceeding <link>
                    link_tags[startAt].insert_before(new_paths)
                else:  # insert before the comments preceeding <link>
                    furthest_comment.insert_before(new_paths)
        else:
            link_tags[-1].insert_after(new_paths)  # add after last <link>


def modify_path(path, rel):
    """
    Evaluates a path against some relative path.

    :param str path: path to evaluate
    :param str rel: a rel path to evaluate 'path' against
    :return: str the evaluated path
    :example:
        path="./assets/css/style1.css"
        rel="../../"
        returns "../../assets/css/style1.css"
    """
    return os.path.normpath(rel + path)


def update_path(tag, rel):
    """
    Updates the 'src' or 'href' attr in a BeautifulSoup4
    tag to account for a relative path. (note: ignores
    'href' attrs that are URLs)

    :param BeautifulSoup4 tag: the tag to update
    :param str rel: rel path to update 'href' or 'src' against
    :return None: modifies tag permenantly
    :example:
        tag representing : <a href="./index.html">
        rel = "../../"
        updates tag to: <a href="../../index.html">
    """
    if tag.has_attr("src"):
        updated_path = modify_path(tag["src"], rel)
        tag["src"] = updated_path
    elif tag.has_attr("href") and not (
        tag["href"].startswith("http") or tag["href"].startswith("#")
    ):
        updated_path = modify_path(tag["href"], rel)
        tag["href"] = updated_path


def update_paths(soup, rel):
    """
    Updates paths in all <link>, <script>, and <a>
    tags in a BeautifulSoup object to account for some
    relative path.
    Caution: Result depends on OS running script.


    :param BeautifulSoup4 soup: the bs4 object to update
    :param str rel: rel path to update paths against
    :return: None (modifies soup permenantly)
    :example:
        for soup representing this page:
            <head>
                <link href="./assets/css/style1.css">
                <script src="./assets/js/scripts.js">
            </head>
        rel="../"

        modified soup (if running on POSIX system):
            <head>
                <link href="../assets/css/style1.css">
                <script src="../assets/js/scripts.js">
            </head>
        modified soup (if running on Windows system):
            <head>
                <link href="..\\assets\\css\\style1.css">
                <script src="..\\assets\\js\\scripts.js">
            </head>
    """
    tags = soup.find_all(["link", "script", "a"])
    for tag in tags:
        update_path(tag, rel)


def update_path_unix(tag):
    """
    If tag has href or src attr, converts
    any file seperators for the operating
    system to / file separators

    :param BeautifulSoup4 tag: the tag to update
    :return None: modifies tag permenantly
    """
    if tag.has_attr("src"):
        updated_path = unix_filepath(tag["src"])
        tag["src"] = updated_path
    elif tag.has_attr("href") and not (
        tag["href"].startswith("http") or tag["href"].startswith("#")
    ):
        updated_path = unix_filepath(tag["href"])
        tag["href"] = updated_path


def update_paths_unix(soup):
    """
    Updates paths in all <link>, <script>, and <a>
    tags in a BeautifulSoup object so that they are
    in Unix filenotation. (Windows \\ separators
    will result in w3 validation errors)

    :param BeautifulSoup4 soup: the bs4 object to update
    :return: None (modifies soup permenantly)
    """
    tags = soup.find_all(["link", "script", "a"])
    for tag in tags:
        update_path_unix(tag)


def unix_filepath(path):
    """
    In a string, replace all path separators
    of the OS to Unix path separator

    :param String path: Stirng to replace
        file seperators in
    :return String: path with any occurances
        of the native OS's file path seperators
        to /
    """
    return path.replace(os.sep, "/")


def make_soup(html_str):
    """
    convert a string to a BeautifulSoup4 object

    :param str html_str: string of (hopefully) valid HTML
    :return: BeautifulSoup4 object for the string
    """
    soup = BeautifulSoup(html_str.encode(ENC), "html.parser")
    return soup


def make_soup_from_file(filepath, log=True):
    """
    convert a file to a beautifulSoup4 object

    :param str filepath: absolute path to file to read
    :param boolean log: print steps to stdout
    :return: BeautifulSoup4 object for data in the file
    """
    if log:
        print(
            "\t\tbeautiful_soup_utils: Generate soup "
            "from file \n\t\t\t{}".format(filepath)
        )
    if not os.path.abspath(filepath):
        raise Exception(
            (
                "ERROR (beautiful_soup_utils) filepath to get soup from is not "
                "absolute {}"
            ).format(filepath)
        )
    if not os.path.exists(filepath):
        raise Exception(
            (
                "ERROR (beautiful_soup_utils) filepath to get soup from does "
                "not exist {}"
            ).format(filepath)
        )
    file_str = read_file(Path(filepath))
    soup = make_soup(file_str)
    return soup


def restore_html_entities(string, fix_yelochki=False):
    """
    Custom formatter for BeautifulSoup prettify().

    When passed as formatter=restore_html_entities to prettify(),
    every string and attribute value in the parse tree will be
    passed to this function, and prettify will output whatever
    value it returns.

    Necessary because none of BeautifulSoup's built-in formatter
    options handle both Cyrillic characters and HTML entities
    correctly:
        - formatter='html' or 'html5': preserves &nbsp; but mangles
          Cyrillic (e.g. replaces them with numeric entities like
          &#1084;)
        - formatter='minimal' or None: preserves Cyrillic but
          strips &nbsp; and other HTML entities

    Since no built-in formatter does both, this custom formatter
    re-escapes the characters that BeautifulSoup decoded during
    parsing (&nbsp; → \\xa0, &lt; → <, etc.) back to their entity
    forms, while leaving Cyrillic and other Unicode characters
    untouched.

    Uses BeautifulSoup's own EntitySubstitution.substitute_html()
    to perform the conversion. The set of characters to restore
    is defined in _ENTITIES_TO_RESTORE.
    """
    # Characters that BeautifulSoup decodes during parsing and must be
    # re-escaped to their HTML entity forms before writing to disk.
    # Each entry is the decoded character that EntitySubstitution will
    # convert back to its entity form.
    # Source: bs4.dammit.EntitySubstitution.substitute_html
    #
    # IMPORTANT: & must be restored FIRST. If it runs after the others,
    # it will convert the & in &lt;, &gt;, &nbsp;, etc. into &amp;lt;,
    # &amp;gt;, &amp;nbsp; — double-encoding and breaking the output.
    #
    # Uses BeautifulSoup's EntitySubstitution.substitute_html() to
    # perform the conversion.
    _ENTITIES_TO_RESTORE = [
        "&",  # &amp;   — must be first; prevents double-encoding of entities below
        "\xa0",  # &nbsp;  — non-breaking space; without it custom spacing collapses
        "<",  # &lt;    — less-than; the browser will misparse <<text>> as HTML tags
        ">",  # &gt;    — greater-than; same as above
        '"',  # &quot;  — double quote; prevents premature termination of attribute values
        "'",  # &apos;  — single quote; same as above
    ]

    # fix guillemets first; will be no << or >> to replace after entity restoration
    if fix_yelochki:
        string = string.replace("<<", "«").replace(">>", "»")

    for char in _ENTITIES_TO_RESTORE:
        string = string.replace(char, EntitySubstitution.substitute_html(char))

    return string


def preserve_nbsp_and_ru(string):
    """
    custom formatter for BeautifulSoup prettify.
    preserves both &nbsp and Cyrillic chars.
    When this function is passed as value to formatter
    arg (i.e. prettify(formatter=preserve_nbsp_and_ru))
    then every String and attribute value encountered
    will be passed to it; prettify will output
    whatever value it returns.

    necessary, because:
        - if you don't supply a formatter arg, &nbsp are removed
        - if you supply formatter='html', &nbsp are preserved, but
            Cyrillic gets mangled.
        - Note: prettify 'formatter' arg takes only 5 values:
            (1) "minimal" (removes &nbsp; preserves Cyrillic),
            (2) "html" (preserves &nbsp; mangles Cyrillic),
            (3) "html5" (same as 'html', just doesn't add trailing /
                on void tags, to conform with html5 rules
                [i.e. generates <br> rather than <br/>])
            (4) None (removes &nbsp; preseves Cyrillic)
                [but docs warn it can generate bad HTML]
            (5) custom function.

    SO I posted about this:
    https://stackoverflow.com/questions/69790205/prettify-with-beautifulsoup-using-a-formatter-that-will-preserve-nbsp-and-cyril/69790637#69790637
    """

    newstr = ""
    # split on nbsp
    # (&nbsp are parsed in BS as \xa0)
    # (https://stackoverflow.com/questions/66895175/beautifulsoup-find-tag-with-text-containing-nbsp)
    split_str = string.split("\xa0")
    # (this will split a&nbsp;b&nsbp;&c --> [a,b,c])
    for i, space_between in enumerate(split_str):
        # space_between will be regular text
        newstr += space_between
        # add an &nbsp after it, unless you're on the last
        # item in the list, after which there would not be an &nbsp
        if i < len(split_str) - 1:
            # put the nbsp through the EntitySubstitution function
            # which will preserve it
            newstr += EntitySubstitution.substitute_html("\xa0")
    return newstr


def prettify_soup(
    soup,
    preserve_ru=True,
    preserve_html_entities=True,
    fix_yelochki=False,
    taglist=[],
    taglist_outer=[],
    remove_trailing_backslash=False,
):
    """
    prettify a BeautifulSoup4 object

    :param BeautifulSoup4 soup: BeautifulSoup object to prettify
    :param boolean preserve_ru: preserve Cyrillic when prettifying
    :param boolean preserve_html_entities: optional preserve
        HTML entities (&nbsp;, &gt;, etc.) while prettifying.
    :param boolean fix_yelochki: convert <<, >> to «, »
        while prettifying
    :param list[str] taglist: optional. list of HTML tags to
        collapse whitespace chars inside. i.e. ["em", "h1", "span"]
    :param list[str] taglist_outer: optional list of tags to
        collapse whitespace chars OUTSIDE of i.e. ["em", "h1", "span"]
    :param boolean remove_trailing_backslash: if True, remove
        trailing /> on void tags (a w3 validation warning)
    :return: prettified STRING for soup
    """
    if fix_yelochki and not (preserve_ru and preserve_html_entities):
        raise ValueError(
            "prettify_soup: fix_yelochki requires both preserve_ru=True and "
            "preserve_html_entities=True, because guillemet conversion "
            "is performed by the custom formatter (restore_html_entities), "
            "which is only used when both options are enabled.\n"
            "\n"
            "If you need guillemet conversion with a different formatter "
            "(e.g. 'html5' or 'minimal'), pre-process your content before "
            "passing it to BeautifulSoup by replacing << and >> with « and » "
            "in the raw HTML string."
        )

    formatter = "minimal"  # default formatter for prettify: preserves cyrillic but removes &nbsp;
    if preserve_ru and preserve_html_entities:
        # prettify(formatter=...) expects a callable taking exactly one
        # argument (the string). Use a lambda to pass fix_yelochki
        # through to restore_html_entities, since the formatter API
        # doesn't support extra arguments.
        formatter = lambda s: restore_html_entities(s, fix_yelochki=fix_yelochki)
    elif preserve_html_entities:
        formatter = "html5"  # preserves &nbsp; but mangles Cyrillic; no trailing / on void tags like <br>

    soup_str = soup.prettify(formatter=formatter)
    for tag in taglist:
        soup_str = collapse_tags_inner(soup_str, tag)
    for tag in taglist_outer:
        soup_str = collapse_tags_outer(soup_str, tag)
    if remove_trailing_backslash:
        soup_str = fix_void_tags(soup_str)
    return soup_str


def fix_void_tags(html):
    """
    remove trailing "/" on void tags
    (BeautifulSoup adds / to end of void tags at prettify, i.e. <br/>,
    unless formatter=html5 or formatter=None, but they mangle Cryrillic.
    So, adding function to remove trailing / on void tags only.)
    Note: do NOT remove all /> - that's valid to close non-void tags,
    and can mangle your HTML (e.g. <path> as subset of <svg>)
    """
    void_tags = [
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    ]
    for tag in void_tags:
        closing_slash_reg = re.compile(f"<{tag}(.*)/>")
        html = closing_slash_reg.sub(f"<{tag}\\1>", html)
    return html


def collapse_tags_outer(html, tag):
    """
    removes whitespace OUTSIDE an HTML tag. i.e.:
    <div>
        <span>
            text
        </span>
    </div>
    returns:
    <div><span>
            text
         </span></div>

    WARNING: Proceed at own risk.

    :param str html: str of html to collapse whitespaces in
    :param str tag: tag in the html to collapse whitespace in
        (i.e. "em" , "span", etc.)
    :return str with whitespace collapsed around the tags
    """

    # remove space chars BEFORE opening tag
    # (be mindful of attrs, i.e. <tag class="..")
    # https://stackoverflow.com/questions/6711567/how-to-use-python-regex-to-replace-using-captured-group
    reg_tag = re.compile(f"\\s*<{tag}([^>]*)>\\s*")
    html = reg_tag.sub(f"<{tag}\\1>", html)
    # replace spaces AFTER closing tag
    # https://stackoverflow.com/questions/55962146/remove-line-breaks-and-spaces-around-span-elements-with-python-regex
    # (note: that SO answer didn't entirely work; maybe because of the +
    # it was ignoring </span> tags that only had a newline around one side)
    html = re.sub(f"</{tag}>\\s*", f"</{tag}>", html)
    return html


def collapse_tags_inner(html, tag):
    """
    find tags of a given type in an HTML string (i.e. <h1>)
    and collapse any whitespace chars inside those tags

    WARNING: Proceed at own risk.

    :param str html: str of html to collapse whitespaces in
    :param str tag: tag in the html to collapse whitespace in
        (i.e. "em" , "span", etc.)
    :return str with whitespace collapsed inside tags
    """
    # remove spaces AFTER opening tag
    # (be mindful of attrs, i.e. <tag class="..")
    # https://stackoverflow.com/questions/6711567/how-to-use-python-regex-to-replace-using-captured-group
    reg_open = re.compile(
        f"<{tag}([^>]*)>\\s*"
    )  # ([^>]*) captures 0 or more of everything BUT ">" char
    html = reg_open.sub(f"<{tag}\\1>", html)
    # replace spaces BEFORE closing tag.
    html = re.sub(f"\\s*</{tag}>", f"</{tag}>", html)
    return html


def remove_html_comments(soup, preserve_internal):
    """
    remove HTML comments from a BeautifulSoup object

    :param BeautifulSoup4 soup: soup to remove comments from
    :param boolean preserve_internal: if True, dont' remove
        comments added by beautiful_soup_utils.py functions.
    :return: None (modifies soup)
    """
    comments = soup.find_all(string=lambda text: isinstance(text, Comment))
    for comment in comments:
        if preserve_internal and COMMENT_PREFIX in comment.string:
            continue
        comment.extract()


def write_soup_to_file(
    soup,
    output_filename,
    force,
    preserve_ru=False,
    preserve_html_entities=True,
    fix_yelochki=False,
    taglist=[],
    taglist_outer=[],
    log=True,
    remove_trailing_backslash=False,
    remove_comments=False,
    preserve_internal=False,
):
    """
    write a BeautifulSoup object to a file (prettified)

    :param BeautifulSoup4 soup: soup to write to file
    :param str output_filename: absolute path to file
        to write to.
    :param boolean force: Overwrite if files exists
    :param boolean preserve_ru: optional. preserve Cyrillic
        while prettifying
    :param boolean preserve_html_entities: optional preserve
        HTML entities (&nbsp;, &gt;, etc.) while prettifying.
    :param boolean fix_yelochki: convert <<, >> to «, »
        while prettifying
    :param list[str] taglist: optional list of tags to
        collapse whitespace chars inside of during prettify
        i.e. ["h1", "span", "em"]
    :param list[str] taglist_outer: optional list of tags to
        collapse whitespace chars OUTSIDE of during prettify
        i.e. ["h1", "span", "em"]
    :param boolean log: print steps to stdout
    :param boolean remove_trailing_backslash: if True, remove
        trailing /> on void tags (a w3 validation warning)
    :param boolean remove_comments: if True, removes HTML comments
    :param boolean preserve_internal: if remove_comments=True
        and this is True, then removes all comments EXCEPT
        ones added internally by functions in this library,
        else removes those too. if remove_comments=False,
        then this option is not used.
    :return: None
    """
    if log:
        print(
            "\t\tbeautiful_soup_utils: Prettify soup "
            "and write to\n\t\t\t{}".format(output_filename)
        )
    if remove_comments:
        remove_html_comments(soup, preserve_internal)
    pretty_soup = prettify_soup(
        soup,
        preserve_ru,
        preserve_html_entities,
        fix_yelochki,
        taglist,
        taglist_outer,
        remove_trailing_backslash,
    )
    write_file(pretty_soup, Path(output_filename), force)
