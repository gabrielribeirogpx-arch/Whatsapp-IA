type LeadDisplayNameSource = {
  contact_name?: string | null;
  contact?: { name?: string | null; display_name?: string | null } | null;
  name?: string | null;
  phone?: string | null;
};

function nonEmptyText(value: unknown): string | null {
  if (typeof value !== 'string') return null;
  const normalized = value.trim();
  return normalized || null;
}

export function formatLeadPhone(phone: string | null | undefined): string | null {
  const raw = nonEmptyText(phone);
  if (!raw) return null;

  const digits = raw.replace(/\D/g, '');
  if (digits.length === 13) return `+${digits.slice(0, 2)} (${digits.slice(2, 4)}) ${digits.slice(4, 9)}-${digits.slice(9)}`;
  if (digits.length === 12) return `+${digits.slice(0, 2)} (${digits.slice(2, 4)}) ${digits.slice(4, 8)}-${digits.slice(8)}`;
  if (digits.length === 11) return `(${digits.slice(0, 2)}) ${digits.slice(2, 7)}-${digits.slice(7)}`;
  if (digits.length === 10) return `(${digits.slice(0, 2)}) ${digits.slice(2, 6)}-${digits.slice(6)}`;
  return raw;
}

/** Resolves an identity only; message previews are intentionally not candidates. */
export function resolveLeadDisplayName(lead: LeadDisplayNameSource): string {
  return (
    nonEmptyText(lead.contact?.display_name) ||
    nonEmptyText(lead.contact?.name) ||
    nonEmptyText(lead.contact_name) ||
    nonEmptyText(lead.name) ||
    formatLeadPhone(lead.phone) ||
    'Contato sem nome'
  );
}
