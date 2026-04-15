type AvatarProps = {
  name?: string | null;
  avatarUrl?: string | null;
};

export default function Avatar({ name, avatarUrl }: AvatarProps) {
  if (avatarUrl) {
    return <img src={avatarUrl} alt={`Avatar de ${name || 'contato'}`} className="wa-avatar-image" />;
  }

  const firstLetter = name?.trim().charAt(0).toUpperCase();

  if (firstLetter) {
    return <div className="wa-avatar-fallback wa-avatar-fallback-initial">{firstLetter}</div>;
  }

  return <div className="wa-avatar-fallback wa-avatar-fallback-icon">👤</div>;
}
