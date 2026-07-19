import type { ReactNode } from 'react';
import Link from 'next/link';
import { ChevronLeft, MoreHorizontal } from 'lucide-react';

export function ResponsivePageHeader({ title, description, eyebrow, primaryAction, secondaryActions, backHref, compactOnMobile = false }: {
  title: string; description?: string; eyebrow?: string; primaryAction?: ReactNode; secondaryActions?: ReactNode; backHref?: string; compactOnMobile?: boolean;
}) {
  return <header className={`responsive-page-header ${compactOnMobile ? 'responsive-page-header--compact' : ''}`}>
    <div className="responsive-page-header__copy">{backHref ? <Link href={backHref} className="responsive-page-header__back" aria-label="Voltar"><ChevronLeft size={20} /></Link> : null}<div>{eyebrow ? <span className="responsive-page-header__eyebrow">{eyebrow}</span> : null}<h1>{title}</h1>{description ? <p>{description}</p> : null}</div></div>
    {(primaryAction || secondaryActions) ? <div className="responsive-page-header__actions" aria-label="Ações da página"><div className="responsive-page-header__secondary">{secondaryActions}</div>{primaryAction}<span className="responsive-page-header__more" aria-hidden="true"><MoreHorizontal size={20} /></span></div> : null}
  </header>;
}
