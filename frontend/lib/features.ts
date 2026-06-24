export const ENABLE_GMAIL_INTEGRATION = false;
export const ENABLE_GOOGLE_SHEETS_INTEGRATION = false;

const GOOGLE_SHEETS_TOOL_TERMS = [
  'google sheets',
  'google_sheets',
  'sheets',
  'spreadsheet',
  'planilha',
  'planilhas',
];

export function isGoogleSheetsToolPayload(tool: Record<string, unknown>): boolean {
  const metadata =
    tool.metadata && typeof tool.metadata === 'object'
      ? (tool.metadata as Record<string, unknown>)
      : {};

  const values = [
    metadata.provider,
    tool.id,
    tool.tool_id,
    tool.tool_name,
    tool.display_name,
    tool.name,
    tool.description,
    tool.server_name,
  ];
  const haystack = values
    .filter((value) => value !== undefined && value !== null)
    .map((value) => String(value).toLowerCase())
    .join(' ');

  return GOOGLE_SHEETS_TOOL_TERMS.some((term) => haystack.includes(term));
}

export function filterGoogleSheetsTools<T extends Record<string, unknown>>(tools: T[]): T[] {
  if (ENABLE_GOOGLE_SHEETS_INTEGRATION) return tools;
  return tools.filter((tool) => !isGoogleSheetsToolPayload(tool));
}
