'use client';
import { useEffect } from 'react';
import { NodeProps, useUpdateNodeInternals } from 'reactflow';
import CompactFlowNode from './CompactFlowNode';
const HANDLES = [{id:'success',label:'Sucesso',color:'#16a34a'},{id:'invalid',label:'Inválido',color:'#dc2626'},{id:'timeout',label:'Timeout',color:'#d97706'},{id:'cancel',label:'Cancelar',color:'#64748b'}];
export default function DataCollectionNode({id,data,selected,isConnectable}:NodeProps){
 const update=useUpdateNodeInternals(); const d=(data||{}) as Record<string,unknown>; const options=Array.isArray(d.options)?d.options as Array<Record<string,unknown>>:[];
 useEffect(()=>{const frame=requestAnimationFrame(()=>update(id));return()=>cancelAnimationFrame(frame)},[id,update]);
 return <CompactFlowNode id={id} selected={selected} title="Coleta de Dados" emoji="📥" badge={String(d.data_type||'text').toUpperCase()} badgeTone={{background:'#ecfdf5',color:'#047857'}} accent="linear-gradient(90deg,#10b981,#14b8a6)" summary={`{{${String(d.variable_name||'variavel')}}}`} meta={`${d.required===false?'Opcional':'Obrigatório'} · ${Number(d.max_attempts||3)} tentativas`} statusLabel={d.data_type==='choice'?`${options.length} opções`:'Aguarda resposta'} isConnectable={isConnectable} sourceHandles={HANDLES}/>
}
