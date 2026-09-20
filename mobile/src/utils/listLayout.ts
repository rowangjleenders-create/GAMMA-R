/** Fixed-row helpers for FlatList getItemLayout (smoother scroll). */

export function fixedGetItemLayout(rowHeight: number) {
  return (_: unknown, index: number) => ({
    length: rowHeight,
    offset: rowHeight * index,
    index,
  });
}

/** Watchlist ticker card: padding + one line + Card margin. */
export const WATCHLIST_ROW_HEIGHT = 72;

/** Paper position card with P&L line + Close button. */
export const POSITION_ROW_HEIGHT = 148;

/** Dashboard signal card (typical mom + forward lines). */
export const SIGNAL_ROW_HEIGHT = 108;

/** Dashboard section header strip. */
export const SIGNAL_SECTION_HEADER_HEIGHT = 36;
