# Marketplace modal — visual verification

The automated contract test protects the modal structure, accessible close action,
focus lifecycle, absence of the former assistant label, responsive grid and scroll
container. Run the following browser checks at 100% zoom for final rendering:

## Desktop — 1366 × 768

1. Open the Flow Builder and focus the control that opens **Marketplace**.
2. Open the modal and confirm the header and both filter rows are visible.
3. Confirm the close button is the only X and is 16 px from the top/right edges.
4. Confirm a usable first row of three or four cards is visible.
5. Scroll only the catalog; reach the final card and confirm both CTAs are complete.
6. Hover every top-right control and confirm no floating minimization label appears.
7. Press Tab through every action, then Shift+Tab from the first action; focus must
   remain inside the modal.
8. Press Escape and confirm focus returns to the Marketplace opener.

## Desktop — 1920 × 1080

Repeat the checks above and confirm four cards fit in the first row with both CTAs
visible, plus part of the next row when the catalog contains enough items.

## Mobile — 390 × 844

1. Confirm the modal keeps a 12 px viewport margin and uses one card per row.
2. Horizontally scroll each filter row without moving the page behind the modal.
3. Vertically scroll the catalog through the bottom 32 px padding.
4. Confirm neither CTA nor the last card is covered or clipped.

## DOM audit

With the modal open, run this in DevTools. All three results must be empty/null:

```js
screen.queryByText(['Minimi', 'zar'].join(''));
document.querySelectorAll(`[title="${['Minimi', 'zar'].join('')}"]`);
document.querySelectorAll(`[aria-label="${['Minimi', 'zar'].join('')}"]`);
```
