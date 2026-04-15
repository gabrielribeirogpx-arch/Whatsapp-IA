'use client';

import Link from 'next/link';
import { useEffect, useState } from 'react';

import { getContacts } from '../../lib/api';
import { CRMContact } from '../../lib/types';

export default function CRMPage() {
  const [contacts, setContacts] = useState<CRMContact[]>([]);
  const [error, setError] = useState('');

  useEffect(() => {
    getContacts().then(setContacts).catch(() => setError('Não foi possível carregar os contatos.'));
  }, []);

  return (
    <main className="dashboard-page">
      <section className="dashboard-hero">
        <div>
          <h1>CRM de Vendas</h1>
          <p>Visão de contatos por estágio e score para priorização comercial.</p>
        </div>
        <Link href="/chat" className="primary-button">
          Abrir chat
        </Link>
      </section>

      {error ? <p className="error-text">{error}</p> : null}

      <section className="crm-table-wrap">
        <table className="crm-table">
          <thead>
            <tr>
              <th>Contato</th>
              <th>Telefone</th>
              <th>Stage</th>
              <th>Score</th>
              <th>Última mensagem</th>
            </tr>
          </thead>
          <tbody>
            {contacts.map((contact) => (
              <tr key={contact.id}>
                <td>{contact.name || 'Sem nome'}</td>
                <td>{contact.phone}</td>
                <td>
                  <span className={`crm-stage crm-stage-${contact.stage.toLowerCase()}`}>{contact.stage}</span>
                </td>
                <td>{contact.score}</td>
                <td>{contact.last_message_at ? new Date(contact.last_message_at).toLocaleString('pt-BR') : '-'}</td>
              </tr>
            ))}
            {!contacts.length ? (
              <tr>
                <td colSpan={5} className="empty-state">
                  Nenhum contato encontrado para este tenant.
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </section>
    </main>
  );
}
