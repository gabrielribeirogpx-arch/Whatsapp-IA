type AvatarProps = {
  name?: string | null;
  avatarUrl?: string | null;
  phone?: string | null;
};

function getInitials(name?: string | null, phone?: string | null) {
  if (name?.trim()) {
    const parts = name.trim().split(/\s+/).filter(Boolean);
    const initials = parts
      .slice(0, 2)
      .map((part) => part[0]?.toUpperCase())
      .join('');

    if (initials) return initials;
  }

  const digits = phone?.replace(/\D/g, '') || '';
  return digits.slice(-2) || '--';
}

function pastelColorFromSeed(seed: string) {
  let hash = 0;

  for (let i = 0; i < seed.length; i += 1) {
    hash = (hash << 5) - hash + seed.charCodeAt(i);
    hash |= 0;
  }

  const hue = Math.abs(hash) % 360;
  return `hsl(${hue} 68% 82%)`;
}

export default function Avatar({ name, avatarUrl, phone }: AvatarProps) {
  if (avatarUrl) {
    return <img src={avatarUrl} alt={`Avatar de ${name || 'contato'}`} className="wa-avatar-image" />;
  }

  const initials = getInitials(name, phone);
  const color = pastelColorFromSeed(`${name || ''}-${phone || ''}`);

  return (
    <div className="wa-avatar-fallback" style={{ backgroundColor: color }} aria-label="Avatar fallback">
      {initials}
    </div>
  );
}
