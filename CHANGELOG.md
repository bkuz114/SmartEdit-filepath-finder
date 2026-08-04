# Changelog

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
