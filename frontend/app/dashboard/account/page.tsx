'use client';
import Link from 'next/link';
import { useEffect, useState } from 'react';
import { getMyAccountProfile } from '../../../lib/api';

type AccountProfile = { tenant_id: string; slug: string; name: string; phone_number_id: string; plan: string; language: string };

export default function AccountPage() {
  const [profile, setProfile] = useState<AccountProfile | null>(null);
  useEffect(() => { void getMyAccountProfile().then(setProfile).catch(() => setProfile(null)); }, []);
  const logout = () => { localStorage.removeItem('tenant'); localStorage.removeItem('token'); localStorage.removeItem('tenant_id'); window.location.href = '/login'; };
  return <main style={{ padding: 24 }}><h1>Minha Conta</h1>{profile ? <ul><li><strong>Nome:</strong> {profile.name}</li><li><strong>Slug:</strong> {profile.slug}</li><li><strong>Tenant ID:</strong> {profile.tenant_id}</li><li><strong>Phone Number ID:</strong> {profile.phone_number_id}</li><li><strong>Plano:</strong> {profile.plan}</li><li><strong>Idioma:</strong> {profile.language}</li></ul> : <p>Não foi possível carregar os dados.</p>}<div style={{ display: 'flex', gap: 12 }}><Link href="/dashboard/settings">Configurações</Link><button onClick={logout}>Sair</button></div></main>;
}
