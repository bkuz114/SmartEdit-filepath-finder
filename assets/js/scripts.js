/**
 * Scene Tree Report — Scripts
 *
 * Provides:
 *   - Click-to-toggle on folder / scene-with-children nodes
 *   - "Expand All" / "Collapse All" buttons in the header
 *
 * All state is driven by the presence of the `.collapsed` CSS class
 * on `<li class="tree-node has-children">` elements.  No frameworks,
 * no persistent state — the page loads fully expanded by default.
 */
(function() {
    'use strict';

    /* ---- DOM refs ---------------------------------------- */
    const expandAllBtn = document.getElementById('expand-all');
    const collapseAllBtn = document.getElementById('collapse-all');
    const treeContainer = document.querySelector('.tree');

    /* Safety: bail if the tree isn't on the page */
    if (!treeContainer) return;

    /* ---- Helpers ----------------------------------------- */

    /**
     * Determine whether a click target is a source link
     * (in which case we let the browser navigate instead of toggling).
     */
    function isSourceLink(el) {
        return el.closest('.source-link') !== null;
    }

    /**
     * Find the closest collapsible tree-node ancestor.
     * Only matches nodes with both .has-children and .expandable
     * (the root node has children but is not expandable).
     * Returns null if the click didn't land on a collapsible node.
     */
    function getExpandableNode(el) {
        return el.closest('.tree-node.has-children.expandable');
    }

    /* ---- Toggle single node ------------------------------ */

    /**
     * Click handler for the tree container.
     * Toggles the .collapsed class on a collapsible node when its
     * .node-content row is clicked.  Only nodes with both .has-children
     * and .expandable are eligible — the root node and leaf nodes
     * are ignored. (leaf nodes don't have .has-children, and root
     * node doesn't have .expandable)
     * Source link clicks pass through without toggling.
     */
    treeContainer.addEventListener('click', function(e) {
        if (isSourceLink(e.target)) return;

        /* Only toggle when the click lands on the node's own
           content row, not on a nested child node. */
        const contentRow = e.target.closest('.node-content');
        if (!contentRow) return;

        const node = contentRow.closest('.tree-node.has-children.expandable');
        if (!node) return;

        /* Guard: ensure the content row belongs directly to this
           node, not to a deeper nested node bubbling up. */
        if (contentRow.parentNode !== node) return;

        e.preventDefault();
        node.classList.toggle('collapsed');
    });

    /* ---- Expand / Collapse all --------------------------- */

    /**
     * Return all collapsible nodes in the tree.
     * Excludes nodes that have children but are not marked expandable
     * (e.g. the root node), so Expand All / Collapse All leave the
     * top-level hierarchy visible.
     */
    function getAllExpandableNodes() {
        return treeContainer.querySelectorAll('.tree-node.has-children.expandable');
    }

    if (expandAllBtn) {
        expandAllBtn.addEventListener('click', function() {
            getAllExpandableNodes().forEach(function(n) {
                n.classList.remove('collapsed');
            });
        });
    }

    if (collapseAllBtn) {
        collapseAllBtn.addEventListener('click', function() {
            getAllExpandableNodes().forEach(function(n) {
                n.classList.add('collapsed');
            });
        });
    }
})();