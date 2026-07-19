import type { ReactNode } from 'react';

export function MobilePageContainer({ children, className = '', scroll = 'page', bottomNavigation = true }: {
  children: ReactNode; className?: string; scroll?: 'page' | 'internal' | 'none'; bottomNavigation?: boolean;
}) {
  return <div className={`mobile-page-container mobile-page-container--${scroll} ${bottomNavigation ? '' : 'mobile-page-container--no-nav'} ${className}`}>{children}</div>;
}
