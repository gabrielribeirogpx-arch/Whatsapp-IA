import { SVGProps } from 'react';

function IconBase(props: SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8} aria-hidden="true" {...props} />
  );
}

export function IconMenu(props: SVGProps<SVGSVGElement>) {
  return (
    <IconBase {...props}>
      <path strokeLinecap="round" d="M4 6h16M4 12h16M4 18h16" />
    </IconBase>
  );
}

export function IconClose(props: SVGProps<SVGSVGElement>) {
  return (
    <IconBase {...props}>
      <path strokeLinecap="round" d="M6 6l12 12M18 6L6 18" />
    </IconBase>
  );
}

export function IconChip(props: SVGProps<SVGSVGElement>) {
  return (
    <IconBase {...props}>
      <rect x="7" y="7" width="10" height="10" rx="2" />
      <path strokeLinecap="round" d="M9 1v3M15 1v3M9 20v3M15 20v3M1 9h3M1 15h3M20 9h3M20 15h3" />
    </IconBase>
  );
}

export function IconChats(props: SVGProps<SVGSVGElement>) {
  return (
    <IconBase {...props}>
      <path d="M6 6h12a3 3 0 013 3v6a3 3 0 01-3 3h-3l-4 3v-3H6a3 3 0 01-3-3V9a3 3 0 013-3z" />
    </IconBase>
  );
}

export function IconUsers(props: SVGProps<SVGSVGElement>) {
  return (
    <IconBase {...props}>
      <circle cx="9" cy="8" r="3" />
      <circle cx="17" cy="9" r="2" />
      <path strokeLinecap="round" d="M3 19a6 6 0 0112 0M13 19a4 4 0 018 0" />
    </IconBase>
  );
}
