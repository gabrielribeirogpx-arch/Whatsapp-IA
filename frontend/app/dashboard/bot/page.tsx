'use client';

import Link from 'next/link';
import { useEffect, useState } from 'react';

import BotForm from '../../../components/bot/BotForm';
import BotList from '../../../components/bot/BotList';
import { createBotRule, deleteBotRule, getBotRules } from '../../../lib/api';
import { BotMatchType, BotRule } from '../../../lib/types';

export default function BotRulesPage() {
  const [rules, setRules] = useState<BotRule[]>([]);
  const [trigger, setTrigger] = useState('');
  const [response, setResponse] = useState('');
  const [matchType, setMatchType] = useState<BotMatchType>('contains');
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');

  async function loadRules() {
    setLoading(true);
    setError('');

    try {
      const data = await getBotRules();
      setRules(data);
    } catch {
      setError('Não foi possível carregar as regras do bot.');
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadRules();
  }, []);

  async function handleCreateRule() {
    setError('');
    setNotice('');

    if (!trigger.trim() || !response.trim()) {
      setError('Preencha trigger e resposta para criar uma regra.');
      return;
    }

    setSaving(true);

    try {
      await createBotRule({
        trigger: trigger.trim(),
        response: response.trim(),
        match_type: matchType
      });

      setTrigger('');
      setResponse('');
      setMatchType('contains');
      setNotice('Regra criada com sucesso.');
      await loadRules();
    } catch {
      setError('Não foi possível criar a regra.');
    } finally {
      setSaving(false);
    }
  }

  async function handleDeleteRule(ruleId: string) {
    const shouldDelete = window.confirm('Deseja realmente deletar esta regra?');
    if (!shouldDelete) return;

    setError('');
    setNotice('');
    setDeletingId(ruleId);

    try {
      await deleteBotRule(ruleId);
      setNotice('Regra deletada com sucesso.');
      await loadRules();
    } catch {
      setError('Não foi possível deletar a regra.');
    } finally {
      setDeletingId(null);
    }
  }

  return (
    <main className="dashboard-page">
      <section className="dashboard-hero">
        <div>
          <h1>Automação (Bot)</h1>
          <p>Gerencie regras de respostas automáticas sem alterar o chat atual.</p>
        </div>
        <div className="dashboard-actions">
          <Link href="/dashboard" className="secondary-button">
            Dashboard
          </Link>
          <Link href="/chat" className="primary-button">
            Abrir chat
          </Link>
        </div>
      </section>

      {error ? <p className="error-text">{error}</p> : null}
      {notice ? <p className="notice-text">{notice}</p> : null}

      <section className="products-layout">
        <BotList rules={rules} loading={loading} deletingId={deletingId} onDelete={handleDeleteRule} />

        <BotForm
          trigger={trigger}
          response={response}
          matchType={matchType}
          saving={saving}
          onTriggerChange={setTrigger}
          onResponseChange={setResponse}
          onMatchTypeChange={setMatchType}
          onSubmit={handleCreateRule}
        />
      </section>
    </main>
  );
}
