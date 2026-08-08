# SmartEdit Writer — SQLite Database Reference

**Version:** 1.0  
**Generated:** 2026-08-08  
**Scope:** Reverse-engineered schema analysis for programmatic access to SmartEdit Writer project data.  
**Applicable Software:** SmartEdit Writer (Windows)  
**Database File:** `<project>/.atomic/atomic.meta`

---

## Table of Contents

1. [Architectural Overview](#architectural-overview)
2. [Table Reference](#table-reference)
   - [MetaData](#metadata)
   - [Documents](#documents)
   - [Files](#files)
   - [DisplayTrees](#displaytrees)
   - [ResearchTree](#researchtree)
   - [DraftTrees](#drafttrees)
   - [DraftLinks](#draftlinks)
   - [Bookmarks](#bookmarks)
   - [Categories](#categories)
   - [Recent](#recent)
   - [BookMeta](#bookmeta)
   - [WorkStats](#workstats)
   - [Charts](#charts)
3. [Enumeration Reference](#enumeration-reference)
   - [ItemType](#itemtype)
   - [Section](#section)
   - [Status](#status)
   - [Documents.Type](#documentstype)
4. [Tree Structure](#tree-structure)
   - [Root Nodes](#root-nodes)
   - [Parent-Child Relationships](#parent-child-relationships)
   - [Research Tree](#research-tree)
   - [Draft Trees](#draft-trees)
5. [File Path Derivation](#file-path-derivation)
6. [SQL Recipes](#sql-recipes)
7. [Upgrade Guide: Extending `db_info()` for Notes and Other Types](#upgrade-guide-extending-db_info-for-notes-and-other-types)

---

## Architectural Overview

SmartEdit Writer stores all project data in a single SQLite database file located at `<project_root>/.atomic/atomic.meta`. The schema follows a **single-table inheritance** pattern centered on the `MetaData` table:

- **`MetaData`** is the hub. Every item in the project — folders, scenes, notes, images, bookmarks, root nodes — is a row in `MetaData`.
- **Extension tables** (`Documents`, `Files`, `Bookmarks`, etc.) attach type-specific properties to items via foreign key references to `MetaData.ID`.
- **Tree tables** (`DisplayTrees`, `ResearchTree`, `DraftTrees`) encode hierarchical relationships between items, each representing a distinct organizational axis.

An item exists if and only if it has a row in `MetaData`. Its type (`ItemType`) determines which extension tables are relevant and whether a corresponding file exists on disk.

### On-Disk File Layout

```
<project_root>/
├── .atomic/
│   └── atomic.meta          # SQLite database
├── Documents/               # ItemType 2 (.docx) and 3 (.rtf)
│   ├── 4.docx
│   ├── 5.rtf
│   └── ...
├── Files/                   # ItemType 6 (images, etc.)
│   ├── 56.jpg
│   └── ...
└── Drafts/                  # Draft snapshots (via DraftLinks)
```

All files are stored flat within their respective directories. The filename is `{MetaData.ID}{extension}` — no subdirectories.

---

## Table Reference

### MetaData

**Central entity table.** One row per item in the project.

| Column | Type | Constraints | Description |
|---|---|---|---|
| `ID` | INTEGER | PRIMARY KEY AUTOINCREMENT NOT NULL DEFAULT 0 | Unique identifier. Also used as the base filename for file-backed items. |
| `ItemType` | INTEGER | NOT NULL DEFAULT 2 | Discriminator column. See [ItemType](#itemtype). |
| `Section` | INTEGER | NOT NULL DEFAULT 1 | Project area. See [Section](#section). |
| `Status` | INTEGER | NOT NULL DEFAULT 1 | Item state. See [Status](#status). |
| `UserDefinedName` | TEXT | NOT NULL | Display name shown in the SmartEdit Writer UI. User-editable, not tied to filenames. |
| `Notes` | TEXT | NOT NULL | User-written notes attached to any item type. |
| `DateCreated` | INTEGER | NOT NULL DEFAULT 0 | Creation timestamp (Windows FILETIME / 100-nanosecond intervals since 1601-01-01). |
| `DateModified` | INTEGER | NOT NULL DEFAULT 0 | Last-modified timestamp (same format as `DateCreated`). |

**Primary Key:** `ID`  
**Index:** `meta_idx` UNIQUE on (`ID`)

> **Note on timestamps:** The values (e.g., `131457945047760515`) are Windows FILETIME. To convert to a Unix timestamp: `(filetime - 116444736000000000) / 10_000_000`. Not needed for file-path mapping, but documented for completeness.

---

### Documents

**Rich text content metadata.** Rows exist only for scenes (`ItemType=2`) and notes (`ItemType=3`).

| Column | Type | Constraints | Description |
|---|---|---|---|
| `ItemId` | INTEGER | NOT NULL | Foreign key to `MetaData.ID`. |
| `Type` | INTEGER | NOT NULL | Mirrors `MetaData.ItemType` for document items. See [Documents.Type](#documentstype). |
| `WordCount` | INTEGER | NOT NULL DEFAULT 0 | Cached word count for the document. |

**Foreign Key:** `ItemId` → `MetaData(ID)` (constraint `item_ref`)  
**Index:** `meta_documents_idx` UNIQUE on (`ItemId`)

---

### Files

**Binary file metadata.** Rows exist for items backed by non-document files (images, etc. — `ItemType=6`).

| Column | Type | Constraints | Description |
|---|---|---|---|
| `ItemId` | INTEGER | NOT NULL | Foreign key to `MetaData.ID`. |
| `Extension` | TEXT | NOT NULL | File extension including the leading dot (e.g., `.jpg`, `.png`). |

**Foreign Key:** `ItemId` → `MetaData(ID)` (constraint `file_item_ref`)  
**Index:** `files_idx` UNIQUE on (`ItemId`)

---

### DisplayTrees

**Primary manuscript hierarchy.** Encodes the tree structure visible in the main SmartEdit Writer UI (Section 1).

| Column | Type | Constraints | Description |
|---|---|---|---|
| `ItemId` | INTEGER | PRIMARY KEY NOT NULL | Foreign key to `MetaData.ID`. One row per item in the tree. |
| `ParentId` | INTEGER | NOT NULL | `MetaData.ID` of the parent item. `0` for root nodes. |
| `Position` | INTEGER | NOT NULL DEFAULT 0 | Ordinal position among siblings (lower = earlier). |
| `Opened` | INTEGER | NOT NULL DEFAULT 1 | Persisted UI state: `1` = expanded, `0` = collapsed. |

**Foreign Key:** `ItemId` → `MetaData(ID)` (constraint `display_item_ref`)  
**Index:** `meta_displaytrees_idx` UNIQUE on (`ItemId`)

**Key behaviors:**
- Root nodes have `ParentId = 0`.
- Any `ItemType` can be a parent (folders, scenes, notes).
- Items from Section 5 (Fragments) also appear in `DisplayTrees` — use `MetaData.Section` to filter.

---

### ResearchTree

**Research material hierarchy.** Same structure as `DisplayTrees`, but for Section 6 (Research) items.

| Column | Type | Constraints | Description |
|---|---|---|---|
| `ItemId` | INTEGER | PRIMARY KEY NOT NULL | Foreign key to `MetaData.ID`. |
| `ParentId` | INTEGER | NOT NULL | `MetaData.ID` of parent. `0` for root. |
| `Position` | INTEGER | NOT NULL DEFAULT 0 | Ordinal position. |
| `Opened` | INTEGER | NOT NULL DEFAULT 1 | UI expand/collapse state. |

**Foreign Key:** `ItemId` → `MetaData(ID)` (constraint `researchtree_item_ref`)  
**Index:** `meta_researchtree_idx` UNIQUE on (`ItemId`)

---

### DraftTrees

**Draft snapshot hierarchy.** Stores a snapshot of the manuscript tree at the time a draft was created.

| Column | Type | Constraints | Description |
|---|---|---|---|
| `ItemId` | INTEGER | PRIMARY KEY NOT NULL | Foreign key to `MetaData.ID` (the draft snapshot item). |
| `ParentId` | INTEGER | NOT NULL | Parent within the draft tree. |
| `Position` | INTEGER | NOT NULL DEFAULT 0 | Ordinal position. |
| `Opened` | INTEGER | NOT NULL DEFAULT 1 | UI state. |

**Foreign Key:** `ItemId` → `MetaData(ID)` (constraint `draft_item_ref`)  
**Index:** `draftTrees_idx` UNIQUE on (`ItemId`)

---

### DraftLinks

**Links live items to their draft counterparts.**

| Column | Type | Constraints | Description |
|---|---|---|---|
| `ID` | INTEGER | PRIMARY KEY NOT NULL | Auto-increment row ID. |
| `ItemId` | INTEGER | NOT NULL | The live/manuscript item. |
| `DraftId` | INTEGER | NOT NULL | The draft snapshot item. |

**Foreign Keys:**
- `ItemId` → `MetaData(ID)` (constraint `draft_links_itemId_ref`)
- `DraftId` → `MetaData(ID)` (constraint `draft_links_parentId_ref`)

**Index:** `draftLinks_idx` UNIQUE on (`ID`)

Draft files are stored in `<project_root>/Drafts/`.

---

### Bookmarks

**URL bookmarks attached to items.** No corresponding file on disk.

| Column | Type | Constraints | Description |
|---|---|---|---|
| `ItemId` | INTEGER | NOT NULL | Foreign key to `MetaData.ID`. |
| `Url` | TEXT | NOT NULL | The bookmark URL. |

**Foreign Key:** `ItemId` → `MetaData(ID)` (constraint `bookmark_item_ref`)  
**Index:** `bookmarks_idx` UNIQUE on (`ItemId`)

---

### Categories

**Tagging/classification system.**

| Column | Type | Constraints | Description |
|---|---|---|---|
| `ID` | INTEGER | PRIMARY KEY AUTOINCREMENT NOT NULL DEFAULT 0 | Row ID. |
| `ItemId` | INTEGER | NOT NULL | Foreign key to `MetaData.ID`. |
| `Category` | INTEGER | NOT NULL | Category identifier (application-defined enum). |

**Foreign Key:** `ItemId` → `MetaData(ID)` (constraint `categories_item_ref`)  
**Index:** `categories_idx` UNIQUE on (`ID`)

---

### Recent

**Recently accessed items for the UI.**

| Column | Type | Constraints | Description |
|---|---|---|---|
| `ItemId` | INTEGER | NOT NULL | Foreign key to `MetaData.ID`. |
| `Position` | INTEGER | NOT NULL | Order in the recent list. |

**Foreign Key:** `ItemId` → `MetaData(ID)` (constraint `recent_ref`)  
**Index:** `recent_idx` UNIQUE on (`ItemId`)

---

### BookMeta

**Project-level key-value metadata.** Not item-specific.

| Column | Type | Constraints | Description |
|---|---|---|---|
| `ID` | TEXT | NOT NULL | Key identifier (application-defined). |
| `Number1` | INTEGER | NOT NULL DEFAULT 0 | Generic numeric value. |
| `Number2` | INTEGER | NOT NULL DEFAULT 0 | Generic numeric value. |
| `String1` | TEXT | NOT NULL DEFAULT '' | Generic string value. |
| `String2` | TEXT | NOT NULL DEFAULT '' | Generic string value. |
| `Date1` | INTEGER | NOT NULL DEFAULT 0 | Generic date value (FILETIME). |
| `Date2` | INTEGER | NOT NULL DEFAULT 0 | Generic date value (FILETIME). |

**Index:** `bookmeta_idx` UNIQUE on (`ID`)

The application interprets the generic column names by convention based on the `ID` key.

---

### WorkStats

**Writing session tracking.** Standalone — no foreign key to `MetaData`.

| Column | Type | Constraints | Description |
|---|---|---|---|
| `ID` | INTEGER | PRIMARY KEY AUTOINCREMENT NOT NULL DEFAULT 0 | Row ID. |
| `WorkDate` | INTEGER | NOT NULL DEFAULT 0 | Session date (FILETIME). |
| `DocumentWordCount` | INTEGER | NOT NULL DEFAULT 0 | Words written in documents. |
| `DocumentCharacterCount` | INTEGER | NOT NULL DEFAULT 0 | Characters written in documents. |
| `FragmentsWordCount` | INTEGER | NOT NULL DEFAULT 0 | Words written in fragments. |
| `FragmentsCharacterCount` | INTEGER | NOT NULL DEFAULT 0 | Characters written in fragments. |
| `DailyWorkingTime` | INTEGER | NOT NULL DEFAULT 0 | Session duration (units unknown). |
| `Status` | INTEGER | NOT NULL DEFAULT 1 | Record state. |

**Index:** `workstats_idx` UNIQUE on (`ID`)

---

### Charts

**Goal/progress tracking.** Standalone — no foreign key to `MetaData`.

| Column | Type | Constraints | Description |
|---|---|---|---|
| `ID` | INTEGER | PRIMARY KEY AUTOINCREMENT NOT NULL DEFAULT 0 | Row ID. |
| `Title` | TEXT | NULL | Chart title. |
| `Name` | TEXT | NULL | Chart name. |
| `StartDate` | INTEGER | NULL DEFAULT 0 | Start date (FILETIME). |
| `EndDate` | INTEGER | NULL DEFAULT 0 | End date (FILETIME). |
| `Month` | INTEGER | NULL DEFAULT 0 | Month filter. |
| `Year` | INTEGER | NULL DEFAULT 0 | Year filter. |
| `WordTarget` | INTEGER | NULL DEFAULT 0 | Word count goal. |
| `TimeTarget` | INTEGER | NULL DEFAULT 0 | Time goal. |
| `Days` | INTEGER | NULL DEFAULT 0 | Day count. |
| `UniqueId` | TEXT | NULL | Unique identifier. |
| `DeleteId` | TEXT | NULL | Deletion tracking. |
| `Type` | INTEGER | NULL DEFAULT 1 | Chart type. |
| `Status` | INTEGER | NULL DEFAULT 1 | Record state. |

**Index:** `charts_idx` UNIQUE on (`ID`)

---

## Enumeration Reference

### ItemType

The discriminator column in `MetaData`. Determines an item's behavior and file backing.

| Value | Name | File-Backed? | Extension Table | On-Disk Directory | File Extension |
|---|---|---|---|---|---|
| 0 | Root node | No | — | — | — |
| 1 | Folder | No | — | — | — |
| 2 | Scene | Yes | `Documents` | `Documents/` | `.docx` |
| 3 | Note | Yes | `Documents` | `Documents/` | `.rtf` |
| 5 | Bookmark | No | `Bookmarks` | — | — |
| 6 | File (image, etc.) | Yes | `Files` | `Files/` | From `Files.Extension` |

**Values not observed in sample data:** 4. This may be unused or reserved.

**Parenting:** Types 0, 1, 2, and 3 can all have children in `DisplayTrees`. Notes and scenes can be container nodes.

---

### Section

Partitions the project into major areas, each with its own root node and tree.

| Value | Name | Root MetaData.ID | Tree Table |
|---|---|---|---|
| 1 | Main Manuscript | 1 | `DisplayTrees` |
| 5 | Fragments | 2 | `DisplayTrees` |
| 6 | Research | 47 | `ResearchTree` |

Root nodes have `ItemType=0` and `ParentId=0` in their respective tree table.

---

### Status

Item state. All observed values in the sample data are `1`.

| Value | Inferred Meaning |
|---|---|
| 1 | Active / visible |
| (other) | Possibly deleted, archived, or hidden |

**Recommendation:** Filter `Status = 1` to exclude soft-deleted items. If you encounter items with other status values, test behavior before assuming.

---

### Documents.Type

Redundant with `MetaData.ItemType` for document items. Observed mapping:

| Documents.Type | MetaData.ItemType | Meaning |
|---|---|---|
| 1 | 2 | Scene |
| 3 | 3 | Note |

**Recommendation:** Use `MetaData.ItemType` as the authoritative source. `Documents.Type` is denormalized and may not cover all cases.

---

## Tree Structure

### Root Nodes

Each Section has a root node identified by `ParentId = 0` in the appropriate tree table:

```
MetaData:
  ID=1,  ItemType=0, Section=1, UserDefinedName="Huckleberry Finn"   → DisplayTrees root
  ID=2,  ItemType=0, Section=5, UserDefinedName="Fragments"          → DisplayTrees root
  ID=47, ItemType=0, Section=6, UserDefinedName="Research"           → ResearchTree root
```

To find the root of a given tree:

```sql
SELECT dt.ItemId, m.UserDefinedName, m.Section
FROM DisplayTrees dt
JOIN MetaData m ON dt.ItemId = m.ID
WHERE dt.ParentId = 0;
```

### Parent-Child Relationships

Children are linked to parents via `DisplayTrees.ParentId` (or `ResearchTree.ParentId` for research). Sibling order is determined by `Position`.

**Example hierarchy (Section 1, partial):**

```
1 (Huckleberry Finn, root)                    ParentId=0, Position=0
├── 6 (Project Notes, folder)                 ParentId=1, Position=0
│   ├── 7 (Brief story outline, note)         ParentId=6, Position=1
│   ├── 25 (Characters, folder)               ParentId=6, Position=2
│   │   ├── 9 (Huck, note)                    ParentId=25, Position=1
│   │   ├── 26 (Jim, note)                    ParentId=25, Position=2
│   │   └── 27 (Tom Sawyer, note)             ParentId=25, Position=3
│   └── 45 (Todo: Today's work, note)         ParentId=6, Position=0
├── 8 (First Draft, folder)                   ParentId=1, Position=1
│   ├── 3 (Chapter 1, folder)                 ParentId=8, Position=1
│   │   ├── 11 (Chapter start, scene)         ParentId=3, Position=1
│   │   ├── 4 (Introducing Huck, scene)       ParentId=3, Position=2
│   │   │   └── 42 (Consider adding, note)    ParentId=4, Position=0  ← scene as parent
│   │   ├── 12 (Miss Watson, scene)           ParentId=3, Position=3
│   │   └── 5 (Notes, note)                   ParentId=3, Position=0
│   ├── 13 (Chapter 2, folder)                ParentId=8, Position=2
│   ├── 14 (Chapter 3, folder)                ParentId=8, Position=3
│   └── 15 (Chapter 4, folder)                ParentId=8, Position=4
```

Key observations:
- Folders (ItemType 1) are the typical container nodes.
- Scenes (ItemType 2) and notes (ItemType 3) can also be parents.
- `Position` values may have gaps; sort numerically, don't assume contiguity.

### Research Tree

Section 6 items use `ResearchTree` instead of `DisplayTrees`. The schema is identical. To traverse the research hierarchy, substitute `ResearchTree` for `DisplayTrees` and filter `MetaData.Section = 6`.

### Draft Trees

`DraftTrees` stores snapshots of the manuscript hierarchy. `DraftLinks` maps each live item to its draft counterpart. Draft files live in `Drafts/`. Not needed for the primary file-path mapping use case; documented for completeness.

---

## File Path Derivation

### Rules

| ItemType | Directory | Filename | Determined By |
|---|---|---|---|
| 2 (Scene) | `<project>/Documents/` | `{ID}.docx` | Hardcoded |
| 3 (Note) | `<project>/Documents/` | `{ID}.rtf` | Hardcoded |
| 6 (File) | `<project>/Files/` | `{ID}{Extension}` | `Files.Extension` (e.g., `.jpg`) |
| 0, 1, 5 | N/A | No file on disk | N/A |

### Python Implementation

```python
from pathlib import Path

EXTENSION_MAP = {
    2: ".docx",   # Scene
    3: ".rtf",    # Note
}

def resolve_file_path(project_path: Path, item_id: int, item_type: int,
                      extension: str | None = None) -> Path | None:
    """
    Return the absolute path to the source file for a file-backed
    MetaData item, or None if the item has no file on disk.

    Args:
        project_path: Root directory of the SmartEdit Writer project.
        item_id: MetaData.ID of the item.
        item_type: MetaData.ItemType of the item.
        extension: File extension including dot (required for ItemType=6,
                   obtained from Files.Extension).

    Returns:
        Absolute Path to the file, or None.
    """
    if item_type in EXTENSION_MAP:
        return project_path / "Documents" / f"{item_id}{EXTENSION_MAP[item_type]}"
    elif item_type == 6:
        if extension is None:
            return None
        return project_path / "Files" / f"{item_id}{extension}"
    else:
        return None
```

### SQL Query for All File-Backed Items

```sql
SELECT
    m.ID,
    m.UserDefinedName,
    m.ItemType,
    m.Section,
    m.Status,
    f.Extension
FROM MetaData m
LEFT JOIN Files f ON m.ID = f.ItemId
WHERE m.ItemType IN (2, 3, 6)
  AND m.Status = 1
  AND m.Section = 1        -- main manuscript only; remove for all sections
ORDER BY m.Section, m.ID;
```

---

## SQL Recipes

### Get All Items with Their Tree Position

```sql
SELECT
    m.ID,
    m.ItemType,
    m.UserDefinedName,
    m.Section,
    m.Status,
    dt.ParentId,
    dt.Position,
    d.Type AS DocumentType,
    d.WordCount,
    f.Extension
FROM MetaData m
LEFT JOIN DisplayTrees dt ON m.ID = dt.ItemId
LEFT JOIN Documents d ON m.ID = d.ItemId
LEFT JOIN Files f ON m.ID = f.ItemId
WHERE m.Section = 1          -- main manuscript
  AND m.Status = 1           -- active only
ORDER BY dt.ParentId, dt.Position;
```

### Walk the Tree from a Given Item

```sql
WITH RECURSIVE ancestors AS (
    SELECT ItemId, ParentId, 1 AS depth
    FROM DisplayTrees
    WHERE ItemId = ?           -- starting item ID

    UNION ALL

    SELECT dt.ItemId, dt.ParentId, a.depth + 1
    FROM DisplayTrees dt
    JOIN ancestors a ON dt.ItemId = a.ParentId
)
SELECT m.ID, m.UserDefinedName, m.ItemType, a.depth
FROM ancestors a
JOIN MetaData m ON a.ItemId = m.ID
ORDER BY a.depth DESC;
```

### Get Immediate Children of an Item

```sql
SELECT m.ID, m.UserDefinedName, m.ItemType, dt.Position
FROM DisplayTrees dt
JOIN MetaData m ON dt.ItemId = m.ID
WHERE dt.ParentId = ?
ORDER BY dt.Position;
```

### Count Scenes in a Project (Main Manuscript, Active)

```sql
SELECT COUNT(*)
FROM MetaData
WHERE ItemType = 2
  AND Section = 1
  AND Status = 1;
```
