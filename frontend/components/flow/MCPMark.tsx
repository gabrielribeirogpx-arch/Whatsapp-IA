import type { SVGProps } from 'react';

/** A small workflow-native mark shared by the MCP canvas node and its editor. */
export default function MCPMark(props: SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 24 24" fill="none" aria-hidden="true" {...props}>
      <path d="M7.2 7.4 12 4.6l4.8 2.8v5.5L12 15.7l-4.8-2.8V7.4Z" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" />
      <path d="m12 9.2 4.8-1.8M12 9.2 7.2 7.4M12 9.2v6.5M5.1 16.2l2.1-3.3m11.7 3.3-2.1-3.3" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
      <circle cx="4.2" cy="17.7" r="2" fill="currentColor" />
      <circle cx="19.8" cy="17.7" r="2" fill="currentColor" />
      <circle cx="12" cy="4.3" r="2" fill="currentColor" />
    </svg>
  );
}
