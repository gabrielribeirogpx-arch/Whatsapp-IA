/**
 * Single source of truth for Intelligent Onboarding mission destinations.
 *
 * Keep mission navigation here so the checklist, Wazza assistant, Academy,
 * and any future onboarding entry point cannot drift to different screens.
 */
export const MISSION_ROUTES = {
  company: '/dashboard/account?tab=profile',
  whatsapp: '/dashboard/settings?tab=whatsapp-business&section=connections',
  flow: '/dashboard/flow-builder?create=true',
  message: '/dashboard/inbox',
  inbox: '/dashboard/inbox',
  pipeline: '/dashboard/pipeline',
  ai: '/dashboard/ai-settings',
  publish: '/dashboard/flow-builder',
  team: '/dashboard/account?tab=users',
} as const;

export type OnboardingMissionId = keyof typeof MISSION_ROUTES;

export function getMissionRoute(missionId: OnboardingMissionId) {
  return MISSION_ROUTES[missionId];
}
