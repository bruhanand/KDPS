# KDPS modern retail ERP UI — design research

**Date:** 2026-07-28  
**Scope:** Design principles for a role-aware fashion retail ERP with a frosted sidebar and an opaque white operational workspace.  
**Method:** Primary sources only: Microsoft Fluent/Windows, IBM Carbon, Material Design, SAP Fiori, Shopify, and W3C.

## Executive recommendation

Build KDPS around one calm, restrained frosted navigation layer and an opaque white data workspace. Keep familiar enterprise interaction patterns for navigation, tables, filters, forms, and approvals. Make the product distinct through fashion-retail content: garment thumbnails, colour swatches, size runs, season signals, location-aware stock states, and a warm pastel accent system.

The inspiration screenshots are useful for tone—lightness, rounded geometry, generous grouping, and selective colour—but their low-density project dashboard should not be copied literally into stock, inward, reconciliation, and finance workflows.

## 1. Material and colour

### Safe convention

- Use frost/acrylic to establish hierarchy, not as a universal surface. Microsoft recommends acrylic mainly for transient or supporting UI, warns against layered or adjacent acrylic surfaces, and recommends an opaque background for persistent vertical panes in many cases. Acrylic must also fall back to a solid colour when transparency is unavailable or disabled. ([Microsoft: Acrylic material](https://learn.microsoft.com/en-us/windows/apps/design/style/acrylic))
- Keep the operational canvas white or near-white. Use layering, borders, and small tonal shifts before adding shadows. Fluent describes colour as a hierarchy tool that should emphasize significant items only when necessary. ([Microsoft: Windows design principles](https://learn.microsoft.com/en-us/windows/apps/design/design-principles))
- Pastel does not mean low contrast. Use dark labels and icons on pale fills; reserve a stronger brand treatment for the page's main action.

### KDPS opportunity

Treat the sidebar as the single signature material: edge-attached, tinted, softly blurred, with a subtle inner border and a solid fallback. Keep cards, forms, and tables opaque. Express the clothing identity through seasonal accents, fabric-inspired muted colours, garment imagery, and real product swatches rather than “glass everywhere.”

## 2. Role-aware enterprise navigation

### Safe convention

- Use a persistent shell containing brand, legal entity/store context, global search, notifications, and user controls. SAP's enterprise launchpad is role-based and provides navigation, search, notifications, and personalization in a consistent shell. ([SAP Fiori: Best practices](https://experience.sap.com/fiori-design-web/best-practices-for-designing-sap-fiori-apps/), [SAP Fiori: Launchpad](https://experience.sap.com/fiori-design-web/launchpad/))
- Show only relevant and authorized modules. SAP recommends that role spaces contain only the information and apps people need to begin daily work. Do not fill the sidebar with disabled destinations a user can never access.
- Use stable work-area labels and a strong current-page state. Suggested top-level groups are Overview, Buying & Vendors, Inbound, Inventory, Transfers & Returns, Offers, Payments, Analytics, and Administration.

### KDPS opportunity

Provide curated navigation order, quick actions, landing dashboard, and saved views for Store Operator, Warehouse, Patna Inward, Buyer/Vendor Handler, Accounts, Owner, and Administrator. The shell's store/state-GSTIN context should remain visible because it changes the meaning of stock, tax, and approval data.

## 3. Dense data, search, filters, and bulk actions

### Safe convention

- Give every worklist a consistent anatomy: title and count, saved view, search, filter summary, table settings, export, table, then pagination. Carbon reserves the table toolbar for global actions and recommends no more than five visible actions before overflow. ([IBM Carbon: Data table](https://carbondesignsystem.com/components/data-table/usage/))
- Support sortable headers, row hover, keyboard focus, pagination, configurable columns, and a density choice. Use expanded rows or a side detail surface for progressive disclosure; do not make the list itself a spreadsheet replacement.
- When rows are selected, replace the normal toolbar with a contextual batch-action bar and disable conflicting per-row actions. Carbon recommends this explicit mode change for efficient bulk work. ([IBM Carbon: Data table](https://carbondesignsystem.com/components/data-table/usage/))
- Apply a single simple filter immediately. For several categories or expensive queries, let users compose criteria and press **Apply filters**. Always show an applied-filter count and a clear-all action when filters are collapsed. ([IBM Carbon: Filtering](https://carbondesignsystem.com/patterns/filtering/))
- Save role-relevant views that preserve filters, sort, column visibility/order, and density. SAP analytical pages preserve filter and table/chart configuration as page variants. ([SAP Fiori: Analytical list page](https://experience.sap.com/fiori-design-web/analytical-list-page/))

### KDPS opportunity

Use a product identity cell containing a small garment thumbnail, style name, SKU, colour swatch, and size. Make season, brand, supplier, store/warehouse, stock state, ageing, exception status, and commercial model first-class filters. Use a size × colour matrix on product or allocation detail screens; keep network-wide worklists tabular and scan-friendly.

## 4. Fashion retail inventory workflows

### Safe convention

- Model and display stock at variant × location grain. Shopify treats size/colour combinations as variants and manages inventory for each variant. ([Shopify: Variants](https://help.shopify.com/en/manual/products/variants))
- Separate stock states visibly. A useful baseline is **On hand**, **Available**, **Committed**, **Unavailable**, and **Incoming**; unavailable can include damaged, quality-control, or safety stock. ([Shopify: Inventory states](https://help.shopify.com/en/manual/products/inventory/fundamentals/inventory-states))
- Keep the commercial order distinct from physical movement. Purchase orders record supplier terms; transfers and shipments track movement and receipt. ([Shopify: Purchase orders](https://help.shopify.com/en/manual/products/inventory/purchase-orders))
- Receiving must support barcode input, partial shipments, accepted/rejected quantities, and a visible progress state. Partial receipts remain in progress; rejected goods do not increase destination stock. ([Shopify: Inventory transfers](https://help.shopify.com/en/manual/products/inventory/inventory-transfers/creating-and-managing-transfers))
- Use bulk editing carefully. Shopify notes that absolute quantity bulk edits do not create a movement audit trail; origin/destination adjustments are appropriate when provenance matters. ([Shopify: Bulk inventory adjustments](https://help.shopify.com/en/manual/products/inventory/adjusting-inventory/bulk-editing-inventory))

### KDPS opportunity

Make the dominant hierarchy **style → colour → size → location**. Surface broken size runs, dead/aged stock, low cover, incoming delays, transfer discrepancies, and quarantined pieces before generic totals. Preserve the KDPS document lifecycle and audit trail; muted status colours should support, never replace, explicit labels and quantities.

## 5. Dashboards and progressive disclosure

### Safe convention

- Ship a curated dashboard per role. SAP's role-based launchpad allows users to personalize relevant apps, while overview cards are entry-level previews of a single topic or task. ([SAP Fiori: Launchpad](https://experience.sap.com/fiori-design-web/launchpad/), [SAP Fiori: Overview cards](https://experience.sap.com/fiori-design-web/overview-page-card/))
- Every card should answer a question or lead to work. Cards should not repeat one another, contain full applications, or become editable mini-forms.
- Let users add, hide, and reorder cards after the curated default. Allow resizing only where the content deliberately adapts to reveal more useful detail. ([SAP Fiori: Resizable card layout](https://experience.sap.com/fiori-design-web/resizable-card-layout-overview-page/))
- Preserve context when drilling in: store, date range, brand, and other card filters should carry into the target worklist. ([SAP Fiori: Custom cards](https://experience.sap.com/fiori-design-web/overview-page-custom-cards/))

### KDPS opportunity

Candidate cards include Today's Sales, Pending Inward, Sell-through, Broken Size Runs, Incoming Shipments, Transfer Exceptions, Return Windows, Aged Stock, Payment Approvals, and Best/Worst Stores. Use chart colour sparingly, and always pair visualizations with exact values and a clear drill-in.

## 6. Accessibility acceptance criteria

- Meet WCAG 2.2 AA: normal text at least **4.5:1**, large text at least **3:1**, and meaningful component/state visuals at least **3:1**. ([W3C: WCAG 2.2](https://www.w3.org/TR/WCAG22/), [W3C: Non-text contrast](https://www.w3.org/WAI/WCAG22/Understanding/non-text-contrast))
- Never communicate approval, risk, stock state, or exceptions by colour alone; add text, icon, shape, or pattern. ([W3C: Use of colour](https://www.w3.org/WAI/WCAG22/Understanding/use-of-color))
- Pointer targets must be at least **24 × 24 CSS px** or have sufficient spacing under WCAG AA. For frequent touch workflows, aim for roughly **40–48 px** targets; Material recommends 48 dp touch targets. ([W3C: Target size minimum](https://www.w3.org/WAI/WCAG22/Understanding/target-size-minimum.html), [Material: Accessibility](https://m1.material.io/usability/accessibility.html))
- Provide a persistent, high-contrast keyboard focus indicator and ensure sticky headers, sidebars, toasts, and drawers do not obscure focused controls. ([W3C: Focus not obscured](https://www.w3.org/WAI/WCAG22/Understanding/focus-not-obscured-minimum))
- Test every pastel/frost combination against the least favourable background and in the solid fallback. Support keyboard-only completion, screen-reader labels, text zoom, reduced motion, and high-contrast modes.

## Design decision

**Safe foundation:** familiar role-based shell; opaque white work area; restrained material use; accessible tonal controls; capable saved table views; explicit inventory states; auditable receipt and transfer flows; role-curated dashboards.

**Distinctive KDPS layer:** one signature frosted sidebar, warm fashion-led pastel tokens, product imagery and swatches, style/colour/size structures, exception-first retail signals, and dashboards shaped around how KDPS staff actually begin their day.

