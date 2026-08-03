# Changelog

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
