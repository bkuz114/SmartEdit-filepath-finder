# Changelog

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
