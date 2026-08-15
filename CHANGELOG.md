# Changelog

## 3.0.0 (2026-08-15)

### Added
- `--json` flag for machine-readable tree output. Prints project data
  as JSON to stdout with recursive node serialization. Mutually
  exclusive with `--html`. (ff8c7ae)
- `--json-indent` flag to control JSON pretty-printing (default 2,
  0 for compact output). (dcc6f71)
- `--json-file` flag to write JSON output to a specific file path.
  Can coexist with `--json` (one prints, one saves). (7307c1b)
- `--json-out` flag to trigger JSON file writing, decoupled from
  the path. Enables config file users to specify `json_file` as
  a preference without forcing file output on every invocation.
  (830e369)
- `--console` flag for explicit tree-to-stdout control. Defaults
  to True, auto-adjusted to False when HTML or JSON output is
  active unless explicitly supplied. (3dcfb96)
- ANSI color and style constants for stdout formatting. Error messages
  now use red text with bold for corrective actions. (149aa99, c374e9f)
- Confirmation message with file path printed after HTML report
  generation. (ce6f006)
- `--sort` and `--sort-order` flags for custom tree ordering. Sort
  by any Node attribute (`name`, `date_modified`, `type`, `id`,
  `position`) within each folder. Sorting applies to stdout, HTML,
  and JSON output automatically. (b7589e5)
- `date_modified` attribute on Node, populated from MetaData.DateModified
  with Windows FILETIME to Unix epoch conversion. Available as a sort
  key and included in JSON output. (ad0be63)
- TOML config file support. A config file at `./smartedit_explorer.toml`
  (or specified via `--config-file`) provides persistent defaults for
  any CLI flag. Config keys use argparse dest names. (5f6e9f4)
- `~` expansion in path arguments. Paths like `~/Documents` now
  correctly expand to the user's home directory. (c1a5a9d)
- `any_supplied()` helper for checking whether an argument was
  supplied via CLI or config file. (ee7e718)
- `dump_args()` debug function for inspecting argparse state. (f42c3ac)

### Changed
- `--output` is now always a directory. Report filenames follow
  conventions: `report.html` for merged reports, `<project>.html`
  for individual reports. Previously, `--output` was a file when
  `--merge` was supplied and a directory otherwise — the ambiguity
  caused branching logic and confusing validation. (7307c1b)
- Output modes are now additive. `--html`, `--json`, and
  `--json-out` can coexist in a single invocation. Previously
  they were mutually exclusive via an if/elif/else chain. (03ad6ff)
- `--json-file` can coexist with `--json` (one prints, one saves).
  (9ad3467)
- Default HTML report directory changed from CWD to `./reports/` to
  avoid cluttering the working directory. (9d4f7e8)
- Validation errors now print to stderr and exit with code 1 instead
  of raising exceptions with full tracebacks. (60938aa)
- Config-aware validation: user-supplied flags are validated,
  config-sourced preferences are silently ignored when the
  relevant mode is inactive. (9ce5018, af83b2b, 1772874)
- Path validation now uses resolved values instead of raw args,
  ensuring validation and execution agree for relative paths,
  symlinks, and `~` paths. (7bc91a2, 90ca145)
- Assets reuse message rewritten in plain language for non-technical
  users. (aaa5c15)
- PyPI version badge switched from badge.fury to shields.io for more
  timely updates. (0fcefe6)

### Fixed
- Restored `0` to exit in the interactive project selection prompt,
  removed during the loop refactor. (ef280d2)
- README interactive selection section now documents `0 to exit`
  again. (0fb5fa9)
- Fixed broken `--json-indent` validation that fired on every run
  due to a default value (same class of bug as the --style default
  issue in 1.5.1). (8b5a8c6)
- Fixed completion message printing before HTML file write, which
  caused confusing interleaved output on error. (bd05fe4)
- Fixed post-parse adjustments to account for config-sourced
  values. `--html-output` and `--json-file` now nest correctly
  when `--output` comes from config. (a7ddab0)
- Removed obsolete `--output` validation after directory-only
  refactor. (23fbd15)

### Docs
- Fixed incorrect type annotation in create_HTML_reports() pydoc
  (`tree` key was documented as `dict`, corrected to `Node`).
  (1d36dad)
- Clarified relationship between create_HTML_reports() and
  create_HTML_report() parameter lists. (1d36dad)
- Added section and depth to Node class attribute docstring.
  (2cbac0c)
- Documented `--sort`, `--sort-order`, `--json`, `--json-indent`
  in README options section. (8cda078, ecaf5cf)
- Added section headers to `main()` for readability. (fc3a13d)

## 2.0.3 (2026-08-11)

### Changed
- Removed the interactive re-prompt loop. Previously, after displaying
  a project's output, the script would prompt to select another project.
  With multi-select support (ranges, "all"), users can choose all
  desired projects in one pass. The loop was a relic from when only
  one project could be selected at a time. (16a17a5)
- Removed `0` from the interactive selection options in README since
  there is no longer a loop to exit.

## 2.0.2 (2026-08-11)

### Fixed
- Source file arrows (→) now align to a consistent column in stdout
  tree output. Previously, arrows appeared at different horizontal
  positions depending on tree depth, icon type, and name length.
  (0d3fd76, b9a442f, 8de1ba7, f77a368, 5e5359c, e0be7ed, 0795c40, 2589615)

### Changed
- `display_width()` replaces `len()` for terminal column measurement,
  correctly handling emoji icons that occupy 2 columns and zero-width
  characters like variation selectors. (8de1ba7)
- `_node_display()` is now the single source of truth for stdout node
  rendering, normalizing icon widths across all item types. (8de1ba7)
- Node depth is now tracked as an attribute and kept in sync during
  tree construction, used for connector prefix width calculation.
  (2589615, f77a368)

## 2.0.1 (2026-08-10)

### Fixed
- Corrected `requires-python` from 3.9 to 3.8 in pyproject.toml.
  mammoth supports Python 3.8+, so the stricter requirement
  unnecessarily excluded 3.8 users. (bc3381a)
- README images now use absolute GitHub URLs so they render
  correctly on PyPI. (e48b35d)

## 2.0.0 (2026-08-10)

### Added
- PyPI distribution: install via `pip install smartedit-explorer` (249a3e4)
- `--version` flag to print the version number (70e698f)
- `--help` and `--version` documented in README usage section (8ad1252)
- Screenshot for HTML reports added to README (45e07d4) 
- PyPI badges added to README (c6f4120)

### Changed
- Script renamed from `db_read.py` to `explorer.py` (7bb464f)
- Project restructured to src/ layout for PyPI compatibility (249a3e4)
- beautiful_soup_utils vendored directly instead of via git submodule (249a3e4)
- `main()` no longer requires an args parameter, making it callable programmatically (7336c81)
- Template path passed as parameter instead of referenced as global (8b22967)
- Template moved to `templates/` directory (f1ef0be)
- README restructured with GitHub heading convention and improved narrative flow (b48bd0b, fb54249, 01885bc)
- README updated with pip installation as primary method (01885bc)

### Fixed
- README screenshots now display correctly on PyPI after src/ layout restructure (1a81e1d)

## 1.7.0 (2026-08-10)

### Added
- Multi-section support: the project tree now includes all three
  SmartEdit Writer sections — Manuscript (Section 1), Fragments
  (Section 5), and Research (Section 6). Fragments and Research
  appear as named, collapsible folder nodes with distinct icons
  (🗃️ and 🔬) sorted after manuscript items. (39bc5e2)
- --reuse flag to skip conversion of source files whose converted
  HTML output already exists. Dramatically speeds up repeated
  report generation for large projects. (8c91f3a)

### Fixed
- View links (👁) on expandable container nodes (scenes/notes with
  children) now open correctly instead of toggling the parent node
  (77e0875)
- Source file paths now display correctly in stdout output for
  container nodes that have both children and a source file (ac2c834)

## 1.6.0 (2026-08-09)

### Added
- Note (.rtf) support: notes (ItemType 3) now appear in the project tree
  alongside scenes, with distinct icons (🗒️) and full --convert support
  for inline viewing (1d72d66)
- File attachment support (ItemType 6): user-attached files (images, PDFs,
  etc.) now appear in the project tree with icons (🖼️). File extensions are
  resolved at runtime from the Files table. (e2b3d71)
- Node class with type registry: all item type metadata (icons, CSS classes,
  file extensions, directories) is centralized in Node.\_TYPE_REGISTRY.
  Adding a new SmartEdit Writer item type is a single dict entry. (7e92c74,
  6626888, 717ea45)
- Static helper methods on Node for type queries without instantiation:
  get_extension(), get_file_backed_types(), is_file_backed_type(),
  get_directory(), get_icon(), get_css_class() (6626888)
- Node instance properties (icon, css_class, extension, is_file_backed,
  has_children, is_leaf, is_container, is_root) for clean access in
  rendering code (7e92c74, c0bf6b3, 2611178)
- Emoji icons and proper tree connectors in stdout output (9cc1b56)

### Changed
- Project tree now uses a proper Node-based tree structure instead of
  nested dicts with special "root" keys. db_info() returns a single
  Node root with ordered children. scene_tree() and insert() are
  removed. (4a8e6a9)
- Tree ordering now matches the SmartEdit Writer UI (children sorted
  by DisplayTrees.Position) (4a8e6a9, c835d4b)
- Stdout output modernized with emoji icons and tree-drawing characters
  replacing the old + / - indicators (9cc1b56)
- Print functions renamed from print_scenes/print_project_scenes to
  print_tree/print_project_tree to reflect broader item type support
  (2504693)
- file_from_id() renamed to resolve_SmartEdit_document_filepath() with
  improved error handling (1d72d66, a1c2a5a)

### Fixed
- --style no longer breaks the script when --convert is not supplied.
  The default value for --style caused a spurious validation failure
  on every non-convert run. (8b6a0f4)
- Project name restored in tree output by querying Section 1 root
  name from the database (bbe24e4)

### Removed
- scene_tree() and insert() functions, replaced by single-query
  tree construction in db_info() (4a8e6a9)
- max_length() function, made redundant by tree connector refactor
  (133ffc5)
- Redundant leaf-scene CSS selector for scene icons (0bcc081)

### Refactored
- All docstrings converted to Google style with full type annotations
  (75d363a, d517cec)
- SQLite helper function docstrings expanded with schema context (ed87b40)
- build_li() and \_build_node_classes() now use Node properties instead
  of separate boolean flags (c0bf6b3, 2611178)

## 1.5.1 (2026-08-08)

### Added
- `--style` flag for choosing a CSS theme for converted source files.
  Styles are discovered automatically from `assets/css/converted/`.
  Available themes: accessible, bezumny, colorful, dark, default,
  ebook, manuscript, minimal, newspaper, novel, steampunk. Use
  `--style none` for raw output with no styling. (4e313a7, 8c5cee5)

## 1.5.0 (2026-08-07)

### Added
- `--convert` flag to convert .docx and .rtf source files to HTML for
  inline viewing in the report. Each scene gets a view icon (👁) next to
  its source link. Supports .docx via mammoth and .rtf via striprtf,
  with lazy imports so dependencies are only required when the flag is
  used. (d8abcd7, cd83f69, 994321d, f2edde7)
- `--html-output` flag to specify a custom directory for converted HTML
  files. Defaults to `<output-dir>/html/`. (d8abcd7)
- `--force-html` flag to overwrite existing converted HTML files. (d8abcd7)
- Copy-to-clipboard icon (📋) next to each source file link. Copies the
  full filepath with a brief ✓ confirmation. (8f1880c)
- Progress indicator during file conversion, printing each filename as
  it's processed. (d8abcd7)

### Changed
- Updated vendored beautiful_soup_utils submodule to latest commit,
  bringing in the restore_html_entities custom formatter. This fixes
  a long-standing bug where `<<` and `>>` in Russian text (keyboard
  workarounds for « and ») were being misparsed as HTML tags and
  stripped from the rendered output. (8ae3eeb, b8c991f, 3a7e872)
- Project name sanitization now supports non-ASCII characters (Cyrillic,
  etc.) via `\w` regex with UNICODE flag, preserving project names in
  their original language in directory names. (994321d)

### Fixed
- Converted HTML files for the same project could be split across
  multiple randomly-named directories when the project name contained
  no alphanumeric characters. A per-project directory cache now
  ensures all files for a project land in the same directory. (f2edde7)

### Refactored
- Node rendering unified into a shared `build_li()` function, eliminating
  duplicate source link and content row construction between leaf and
  named nodes. (abe6202)
- `write_soup_to_file` calls converted to named keyword arguments for
  readability and to ease future signature changes. (941a242)

## 1.4.0 (2026-08-05)

### Added
- Multi-project support: `--project` now accepts multiple paths, and
  interactive mode supports comma-separated lists, ranges (e.g. "4-7"),
  and "all" to select every discovered project (560a311, 37b2d02, bb1f252)
- `--merge` flag to combine multiple projects into a single HTML report;
  without it, each project generates its own report file named after
  the project (560a311)
- `--browser` flag to opt-in to opening generated reports in the
  default browser; previously this happened automatically (2a12937)
- Interactive selection now supports range syntax (e.g. "2,4-7,9")
  and "all" keyword; parse errors are collected and displayed together
  rather than failing one at a time (bb1f252, 37b2d02)
- Collapsible project toggle (⊞/⊟) on each project root node in the
  HTML tree, with the entire root row clickable to toggle (52aab8f, fe41fa2)
- Colored book icons for project root nodes, randomly selected from a
  pool; icons are defined via CSS custom properties and assigned via
  class names for easy theming (30bb2c7, 9c9e31d)
- `.tree-root` CSS class on the root `<li>` for clean JS and CSS
  targeting (8968a0d)

### Changed
- Page header now displays a static title ("SmartEdit Writer — Source
  File Map") instead of the project name, accommodating multiple
  projects per report (8ff3a3c)
- Scene count badge moved from the page header to each project root
  node in the tree, displaying per-project counts (1a462f9)
- Source file links floated to the right edge of each row for uniform
  alignment; leaf node hover restored (dimmed) to visually connect
  names to links (72deff9)
- HTML reports now initialize with all projects collapsed for a
  top-level overview (69efd3b)
- Project icon (📚) moved from hardcoded HTML to a CSS custom property
  for consistency with the icon system (9c9e31d)
- Functions renamed for clarity: `project_mapping_HTML` → `create_HTML_report`,
  `print_scenes` → `print_project_scenes` (cb55421, cb17e11)

### Fixed
- 0 rejected as a valid project selection in comma-separated input;
  previously `projects[-1]` would silently return the last project (c638443)
- Invalid project selection warning now preceded by a newline for
  visual separation from the prompt (a1b161d)

### Refactored
- Selection parsing extracted into `get_selections()` with full error
  collection; `chose_projects()` focuses on the interactive prompt loop (bb1f252)
- `is_root` flag extracted in `make_tree_recursive()` to consolidate
  root-specific logic (2c54ac1)
- Functions organized into logical sections with header comments:
  utilities, project discovery, scene mapping, stdout printing,
  HTML tree generation, HTML report generation, asset copying,
  and main driver (405f79c)

## 1.3.0 (2026-08-04)

### Added
- `--output` flag to specify a custom path for the HTML report (3320647)
- `--force` flag to overwrite an existing HTML report (c667665)
- `--force-assets` flag to overwrite an existing assets/ directory at the
  output location, separate from `--force` so users can refresh the report
  without nuking custom CSS/JS (16c945a)
- `--nuclear` flag for aggressive deletion of the assets/ directory on
  Windows when `--force-assets` fails with "Access is denied" errors
  caused by transient file locks (antivirus, search indexer, etc.) (16c945a)
- Automatic copying of assets/ (CSS, JS, favicon) alongside the generated
  HTML report, making it self-contained regardless of output location (16c945a)

### Changed
- Default HTML report output now written to the user's current working
  directory instead of the script directory, matching standard CLI tool
  behaviour and resolving an inconsistency with `--output` relative paths (b877b8c)
- `project_mapping_HTML()` now accepts the output path as a parameter
  instead of hardcoding it internally (cc24f60)
- `main()` moved to end of script to improve readability (5b80b4f)

### Fixed
- `--project` now accepts relative paths (e.g. `../../project_root`) by
  resolving them to absolute before validation (0ba3703)
- `--project` declared as `type=Path` in argparse so conversion is handled
  automatically rather than manually (03bdfda)
- Project path validation (exists, is_dir) now scoped to `--project` only;
  interactively discovered paths are trusted to exist since they were found
  by scanning the filesystem (7a0c582)
- Redundant `is_absolute()` check removed — `Path.resolve()` always returns
  an absolute path (c02376e)
- Redundant `Path()` wrapping removed from `proj_path` — it is already a
  `Path` object in both code paths (dbb9d35)
- `--search-root` now checks existence before `is_dir`, giving users a
  precise error message for non-existent paths (bf24f65)
- `--project` error messages corrected to reference the actual flag name
  instead of the non-existent `--path` (4abc5d1)
- `proj_path` variable reference fixed in `--project` validation error
  messages before the variable was assigned (ab40671)

### Refactored
- String concatenation converted to f-strings throughout the codebase (0e13793)
- Redundant `str()` wrappers removed from f-strings (f877638)
- Removed unused `io_utils` import (a65ef42)
- Added comments clarifying the interactive project selection loop's
  do-while control flow and exit criteria (f998caa)

## 1.2.2 (2026-08-03)

### Changed
- `pathlib.Path` migration (cbaa5ce)
  - Migrated all filesystem path operations from `os.path` to `pathlib.Path`
    for improved readability, type safety, and cross-platform consistency (cbaa5ce)
  - Minimum Python version remains unchanged (pathlib available since Python 3.4;
    BeautifulSoup already requires a newer version)
  - `find_projects()`, `chose_project()`, and `get_project_interactively()`
    now return `Path` objects instead of strings (docstrings updated accordingly)
  - `file_from_id()` now returns `Path` instead of `str`
  - Internal data structures now use `Path` for file paths throughout
    (leaves in the scene tree are now `[Path, str]` instead of `[str, str]`)
- Expand All / Collapse All buttons (db12b57)
  - Replaced dual "Expand All" / "Collapse All" buttons with a single
    toggle button that switches label and style based on tree state
  - Page now initializes fully collapsed for a top-level overview;
    click "Expand All" to reveal the full tree

### Added
- `--norecursive` flag to limit project discovery to the root `SEARCH_ROOT`
  directory without descending into subdirectories (speeds up the search
  when --project is omitted and projects are known to be at the top level)
  (4a19d37)
- `--search-root` argument to specify a custom search directory when
  `--project` is omitted (defaults to the user's Documents folder)
  (b29e8d9) 
- Scene count badge in the HTML report header showing total leaf scenes
  (e.g. "My Novel (47 scenes)") for at-a-glance project scope (6a143b7)
- Added favicon for HTML reports (944106d)

### Fixed
- Added input validation in `chose_project()`: invalid project numbers
  now re-prompt instead of raising `IndexError` or `ValueError` (00bdf78)
- Graceful exit with error message when no SmartEdit Writer projects are found
  (975cead) 
- Root tree node no longer collapses with "Collapse All"; the first level
  of the project hierarchy remains visible for immediate navigation.
  The root is excluded from expand/collapse all via an `.expandable`
  class controlled by Python rather than special-cased in JavaScript.
  (e1d47ef)

## 1.2.1 (2026-08-03)

### Fixed
- SEARCH_ROOT no longer hardcoded to my specific user directory;
  now resolves to the current user's Documents folder via
  os.path.expanduser("~")` for portability across machines
  (so now, if --project arg omitted, all SmartEdit projects rooted in
  user's Documents folder will be found, and script will prompt user
  to select one)

## 1.2.0 (2026-08-03)

### Changed
- Replaced table-based HTML report with semantic collapsible tree
  (nested `<ul>`/`<li>` instead of `<table>` with empty spacer cells)
- Renamed `assets/css/table.css` to `assets/css/style.css` with full
  redesign: CSS custom properties for theming, class-based selectors,
  and clean separation of structure and presentation

### Added
- Collapsible tree nodes with smooth twistie animation (expand/collapse)
- Expand All / Collapse All buttons in the report header
- Visual differentiation for leaf nodes (no hover, muted, no twistie)
- Dark mode support via `prefers-color-scheme` media query
- `assets/js/scripts.js` — vanilla JS for toggle, expand-all, and
  collapse-all behaviour (~45 lines, no dependencies)
- Folder and scene icons (📁 / 📄) via CSS `::before` pseudo-elements
  content on `::before`)

## 1.0.0 (2025-05-11)

### Added
- Initial public release
- Recursive scene tree resolution from SmartEdit Writer SQLite database
- Console output with indented tree view
- HTML report generation with `--html` flag
- Interactive project selection when no `--project` argument given
- `--short` flag for filename-only display
- `--remove` flag to omit project name from tree root
- `--project` flag for direct project path input
