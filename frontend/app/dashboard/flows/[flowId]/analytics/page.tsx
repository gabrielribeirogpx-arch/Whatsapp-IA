'use client';
import Link from 'next/link';
import { useEffect, useMemo, useState } from 'react';
import { Bar, BarChart, CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { getFlowAnalytics } from '@/lib/api';
import { FlowAnalytics } from '@/lib/types';

type Props = { params: { flowId: string } };
const periods = ['24h','7d','30d','90d'];
const empty: FlowAnalytics = { flow_id:'', flow_name:'Flow', period:'7d', summary:{entries:0,messages_sent:0,completed:0,conversion_rate:0,dropoff_rate:0,avg_time_seconds:0,avg_messages_per_user:0}, funnel:[], top_dropoffs:[], common_replies:[], timeline:[], insights:[] };

export default function Page({params}:Props){
const [period,setPeriod]=useState('7d'); const [loading,setLoading]=useState(true); const [data,setData]=useState<FlowAnalytics>(empty);
useEffect(()=>{(async()=>{setLoading(true); try{setData(await getFlowAnalytics(params.flowId,period));}finally{setLoading(false);}})();},[params.flowId,period]);
const kpis=[['Entradas',data.summary.entries],['Conversão',`${data.summary.conversion_rate}%`],['Abandono',`${data.summary.dropoff_rate}%`],['Tempo médio',`${Math.round(data.summary.avg_time_seconds)}s`],['Mensagens/usuário',data.summary.avg_messages_per_user]];
const noData=data.summary.entries===0;
return <div style={{maxWidth:1200,margin:'0 auto',padding:24}}>
<div style={{display:'flex',justifyContent:'space-between',alignItems:'center',gap:12,flexWrap:'wrap'}}><div><h1>Analytics do Flow</h1><div>{data.flow_name} <span style={{padding:'2px 8px',borderRadius:999,background:'#eef2ff'}}>Ativo/OFF</span></div></div><div style={{display:'flex',gap:8}}><Link href='/dashboard/flows'>Voltar</Link>{periods.map(p=><button key={p} onClick={()=>setPeriod(p)}>{p}</button>)}</div></div>
<div style={{display:'grid',gridTemplateColumns:'repeat(5,minmax(0,1fr))',gap:12,marginTop:18}}>{kpis.map(([l,v])=><div key={String(l)} style={{background:'#fff',border:'1px solid #e5e7eb',borderRadius:16,boxShadow:'0 2px 10px rgba(0,0,0,.04)',padding:16}}><div>{l}</div><div style={{fontSize:28,fontWeight:700}}>{v}</div></div>)}</div>
{noData && <div style={{marginTop:16,background:'#fff',border:'1px solid #e5e7eb',borderRadius:16,padding:16}}>Ainda não há dados suficientes. Assim que usuários passarem por este flow, os analytics aparecerão aqui.</div>}
<div style={{marginTop:18,background:'#fff',border:'1px solid #e5e7eb',borderRadius:16,padding:16}}><h3>Funil do Flow</h3>{data.funnel.map((n,i)=>{const color=n.dropoff_rate>40?'#ef4444':n.dropoff_rate>20?'#eab308':'#22c55e';const pct=i===0?100:Math.round((n.entries/(data.funnel[0]?.entries||1))*100);return <div key={n.node_id} style={{marginBottom:12}}><div style={{display:'flex',justifyContent:'space-between'}}><span>{n.node_label} ({n.node_type})</span><span>{pct}%</span></div><div style={{height:8,background:'#f3f4f6',borderRadius:999}}><div style={{height:8,width:`${pct}%`,background:color,borderRadius:999}}/></div><small>Entradas {n.entries} • Dropoff {n.dropoff_rate}% • Conversão próximo {n.conversion_to_next_rate}%</small></div>;})}</div>
<div style={{display:'grid',gridTemplateColumns:'1fr 1fr',gap:12,marginTop:12}}>
<div style={{background:'#fff',border:'1px solid #e5e7eb',borderRadius:16,padding:16}}><h3>Pontos de abandono</h3>{data.top_dropoffs.map(n=><div key={n.node_id}>⚠️ Node “{n.node_label}” — {n.dropoff_rate}% de abandono. Sugestão: simplifique a pergunta.</div>)}</div>
<div style={{background:'#fff',border:'1px solid #e5e7eb',borderRadius:16,padding:16}}><h3>Respostas mais comuns</h3>{data.common_replies.map(r=><div key={r.reply} style={{marginBottom:8}}>{r.reply} — {r.rate}%</div>)}</div></div>
<div style={{marginTop:12,background:'#fff',border:'1px solid #e5e7eb',borderRadius:16,padding:16}}><h3>Performance ao longo do tempo</h3><div style={{height:280}}><ResponsiveContainer><LineChart data={data.timeline}><CartesianGrid strokeDasharray='3 3'/><XAxis dataKey='date'/><YAxis/><Tooltip/><Line dataKey='entries' stroke='#3b82f6'/><Line dataKey='messages_sent' stroke='#22c55e'/><Line dataKey='completed' stroke='#a855f7'/></LineChart></ResponsiveContainer></div></div>
<div style={{marginTop:12,background:'#fff',border:'1px solid #e5e7eb',borderRadius:16,padding:16}}><h3>Insights automáticos</h3>{data.insights.map((i,idx)=><div key={idx}>{i.title}: {i.message}</div>)}</div>
{loading && <div>Carregando...</div>}
</div>}
