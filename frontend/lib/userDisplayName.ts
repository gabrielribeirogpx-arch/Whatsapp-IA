/**
 * Resolves a human-friendly name for a user without relying on technical
 * account identifiers unless there is no profile name available.
 */
export type UserDisplayNameSource = {
  full_name?: string | null;
  name?: string | null;
  first_name?: string | null;
  last_name?: string | null;
  display_name?: string | null;
  username?: string | null;
};

function normalized(value?: string | null): string | undefined {
  const result = value?.trim();
  return result || undefined;
}

export function getUserDisplayName(user?: UserDisplayNameSource | null): string {
  if (!user) return "";

  const fullName = normalized(user.full_name);
  const name = normalized(user.name);
  const firstAndLastName = normalized(
    [normalized(user.first_name), normalized(user.last_name)]
      .filter(Boolean)
      .join(" "),
  );
  const displayName = normalized(user.display_name);
  const username = normalized(user.username);

  return fullName || name || firstAndLastName || displayName || username || "";
}
