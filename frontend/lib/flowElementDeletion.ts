export type SelectableFlowElement = { id: string; selected?: boolean; deletable?: boolean };

export const isFlowEditorTextEntryTarget = (target: EventTarget | null): boolean => {
  if (!(target instanceof Element)) return false;
  if (target.closest('.flow-node-editor-panel')) return true;
  return Boolean(target.closest('input, textarea, select, [contenteditable]:not([contenteditable="false"]), [role="textbox"]'));
};

export const selectedDeletableIds = <T extends SelectableFlowElement>(elements: T[], canvasLocked: boolean): string[] => {
  if (canvasLocked) return [];
  return elements.filter((element) => element.selected && element.deletable !== false).map((element) => element.id);
};

export const isFlowElementDeleteKey = (key: string): boolean => key === 'Delete' || key === 'Backspace';

export const removeElementsById = <T extends { id: string }>(elements: T[], ids: Iterable<string>): T[] => {
  const removedIds = new Set(ids);
  if (removedIds.size === 0) return elements;
  return elements.filter((element) => !removedIds.has(element.id));
};
