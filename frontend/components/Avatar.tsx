type AvatarProps = {
  name?: string | null;
  avatarUrl?: string | null;
  phone?: string | null;
};

function getInitials(name?: string | null, phone?: string | null) {
  if (name?.trim()) {
    const parts = name.trim().split(/\s+/).filter(Boolean);
    const initials = parts.slice(0, 2).map((part) => part[0]?.toUpperCase()).join('');

    if (initials) return initials;
  }

  const digits = phone?.replace(/\D/g, '') || '';
  return digits.slice(-2) || '--';
}

function colorFromSeed(seed: string) {
  const palette = ['#F59E0B', '#3B82F6', '#8B5CF6', '#EC4899', '#14B8A6', '#10B981', '#F97316'];
  let hash = 0;

  for (let i = 0; i < seed.length; i += 1) {
    hash = (hash << 5) - hash + seed.charCodeAt(i);
    hash |= 0;
  }

  return palette[Math.abs(hash) % palette.length];
}

export default function Avatar({ name, avatarUrl, phone }: AvatarProps) {
  if (avatarUrl) {
    return <img src={avatarUrl} alt={`Avatar de ${name || 'contato'}`} className="wa-avatar-image" />;
  }

  const initials = getInitials(name, phone);
  const color = colorFromSeed(`${name || ''}-${phone || ''}`);

  return (
    <div className="wa-avatar-fallback" style={{ backgroundColor: color }} aria-label="Avatar fallback">
      {initials}
    </div>
  );
}
