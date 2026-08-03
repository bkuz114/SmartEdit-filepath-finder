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
     * Find the closest expandable tree-node ancestor.
     * Returns null if the click didn't land on one.
     */
    function getExpandableNode(el) {
        return el.closest('.tree-node.has-children');
    }

    /* ---- Toggle single node ------------------------------ */

    treeContainer.addEventListener('click', function(e) {
        if (isSourceLink(e.target)) return;

        /* Only toggle when the click lands on the node's own
           content row, not on a nested child node. */
        const contentRow = e.target.closest('.node-content');
        if (!contentRow) return;

        const node = contentRow.closest('.tree-node.has-children');
        if (!node) return;

        /* Guard: ensure the content row belongs directly to this
           node, not to a deeper nested node bubbling up. */
        if (contentRow.parentNode !== node) return;

        e.preventDefault();
        node.classList.toggle('collapsed');
    });

    /* ---- Expand / Collapse all --------------------------- */
    function getAllExpandableNodes() {
        return treeContainer.querySelectorAll('.tree-node.has-children');
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