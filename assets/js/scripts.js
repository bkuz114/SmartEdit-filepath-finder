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
    const toggleAllBtn = document.getElementById('toggle-all');
    const treeContainers = document.querySelectorAll('.tree');

    /* Safety: bail if the tree isn't on the page */
    if (!treeContainers) return;

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
     *
     * Handles three click types:
     *   1. root node row - collapses or expands
     *      the entire project. The root doesn't have .expandable, so this
     *      is checked first as a special case.
     *   2. Regular tree node toggle — collapses or expands nodes with both
     *      .has-children and .expandable. Leaf nodes and the root are
     *      excluded.
     *   3. Source links — passed through without toggling.
     *
     * Uses a guard clause to ensure only the clicked node's own content
     * row triggers the toggle, not a nested child node's row bubbling up.
     */
    treeContainers.forEach(treeContainer => {
        treeContainer.addEventListener('click', function(e) {
            if (isSourceLink(e.target)) return;

            /* Toggle project when the root's own content row is clicked.
               Use the direct child selector (> .node-content) to avoid
               matching .node-content elements nested inside child nodes
               (which would incorrectly toggle the project on any click). */
            const rootContentRow = e.target.closest('.tree-root > .node-content');
            if (rootContentRow) {
                e.preventDefault();
                e.stopPropagation();
                const rootNode = rootContentRow.closest('.tree-root');
                const isCollapsed = rootNode.classList.contains('collapsed');
                toggleProject(!isCollapsed, treeContainer);
                return;
            }

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

            /* Sync toggle button in case this was last node of this state */
            syncToggleButton();
        });

        // Initialize: project starts collapsed
        toggleProject(true, treeContainer);
    });

    /* ---- Expand / Collapse all --------------------------- */

    /**
     * Return all collapsible nodes in the tree.
     * Excludes nodes that have children but are not marked expandable
     * (e.g. the root node), so Expand All / Collapse All leave the
     * top-level hierarchy visible.
     */
    function getAllExpandableNodes() {
        let nodes = [];
        treeContainers.forEach(function(treeContainer) {
            nodes.push(...treeContainer.querySelectorAll('.tree-node.has-children.expandable'));
        });
        return nodes;
    }

    /**
     * Expand or collapse all collapsible nodes in the tree
     * @param {boolean} collapsed - true collapses all nodes,
     *   false expands all nodes.
     */
    function toggleAllNodes(collapsed) {
        const nodes = getAllExpandableNodes();
        for (let i = 0; i < nodes.length; i++) {
            nodes[i].classList.toggle('collapsed', collapsed);
        }
    }

    /**
     * Synchronize the toggle-all button with the current tree state.
     *
     * Checks all expandable nodes. If every single node is collapsed,
     * the button switches to "Expand All". If every single node is
     * expanded, it switches to "Collapse All". If nodes are in a mixed
     * state (some expanded, some collapsed), the button keeps its
     * current label — this prevents the button from changing state
     * when only visible top-level nodes appear fully collapsed but
     * deeper nodes remain expanded.
     *
     * Note that this behavior may be confusing to some users:
     * if the top-level nodes are all collapsed (but they have expanded
     * children), then NO nodes will be visible, yet the button would
     * still correctly display "Collapse All". This is correct. Would NOT
     * want to switch to the "Expand All" state because then clicking it
     * would clear the child states that the user had (whereas if they
     * now re-open one of those buttons, the child trees will still
     * be in the same state)
     */
    function syncToggleButton() {
        const nodes = getAllExpandableNodes();
        let allCollapsed = true;
        let allExpanded = true;

        for (let i = 0; i < nodes.length; i++) {
            if (nodes[i].classList.contains('collapsed')) {
                allExpanded = false;
            } else {
                allCollapsed = false;
            }
        }

        if (allCollapsed) {
            updateToggleButton(true);
        } else if (allExpanded) {
            updateToggleButton(false);
        }
    }

    /**
     * Update the toggle button UI.
     * @param {boolean} collapsed - true shows "Expand All",
     *   false shows "Collapse All".
     */
    function updateToggleButton(collapsed) {
        toggleAllBtn.classList.toggle('collapsed-all', collapsed);
    }

    if (toggleAllBtn) {
        toggleAllBtn.addEventListener('click', function() {
            const isCurrentlyCollapsed = toggleAllBtn.classList.contains('collapsed-all');
            const newState = !isCurrentlyCollapsed;
            toggleAllNodes(newState);
            updateToggleButton(newState);
        });
    }

    /* ---- Project Toggle ---------------------------------- */

    /**
     * Collapse or expand the project root node.
     * @param {boolean} collapsed - true collapses the project,
     *   false expands it.
     */
    function toggleProject(collapsed, treeContainer) {
        const rootNode = treeContainer.querySelector('.tree-root');
        if (!rootNode) {
            console.error(`toggleProject: Can't toggle poject. .tree-root not found`);
            return;
        }
        rootNode.classList.toggle('collapsed', collapsed);
        const toggleIcon = rootNode.querySelector('.project-toggle');
        if (toggleIcon) {
            toggleIcon.classList.toggle('collapsed', collapsed);
        }
    }

    // initialize
    toggleAllNodes(true);
    updateToggleButton(true);

})();