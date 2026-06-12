export type DropLead = {
  id: string;
  stage_id?: string | null;
};

export function canMoveLeadToStage<TLead extends DropLead>(
  lead: TLead | null,
  targetStageId?: string | null,
  pendingLeadIds?: ReadonlySet<string>
): lead is TLead {
  if (!lead) return false;
  if (!targetStageId) return false;
  if (lead.stage_id === targetStageId) return false;
  if (pendingLeadIds?.has(lead.id)) return false;
  return true;
}
