import type { RendererOptions } from '@kaggle-environments/core';

interface MainlineEntry {
  card: string;
  rejected: string[];
}

interface Guess {
  words: string;
  code: string;
  error?: string | null;
}

const SUIT_SYMBOL: Record<string, string> = { S: '♠', H: '♥', D: '♦', C: '♣' };

function esc(s: unknown): string {
  return String(s ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
}

function cardHtml(card: string, extra = ''): string {
  const suit = card.slice(-1);
  const red = suit === 'H' || suit === 'D';
  return `<span class="card ${red ? 'red' : 'black'} ${extra}">${esc(card.slice(0, -1))}${SUIT_SYMBOL[suit] ?? suit}</span>`;
}

function mainlineHtml(mainline: MainlineEntry[]): string {
  return mainline
    .map(
      (m) => `<div class="column">${cardHtml(m.card)}${m.rejected.map((r) => cardHtml(r, 'rejected')).join('')}</div>`
    )
    .join('');
}

function lastEventHtml(entry: any): string {
  if (!entry) return '<em>No turns yet</em>';
  if (entry.type === 'play') {
    return `Turn ${entry.turn}: played ${cardHtml(entry.card)} after ${cardHtml(entry.prev)} → <b class="${entry.accepted ? 'ok' : 'bad'}">${entry.accepted ? 'accepted' : 'rejected'}</b>`;
  }
  if (entry.type === 'guess') {
    const verdict = entry.correct ? '<b class="ok">correct</b>' : `<b class="bad">wrong</b>`;
    return `Turn ${entry.turn}: guessed “${esc(entry.words)}” <code>${esc(entry.code)}</code> → ${verdict}${entry.error ? ` (${esc(entry.error)})` : ''}`;
  }
  return `Turn ${entry.turn}: <b class="bad">lost turn</b> (${esc(entry.reason)})`;
}

function thoughtsHtml(agent: any): string {
  const thoughts = agent?.action?.thoughts;
  if (!thoughts) return '';
  return `<details class="thoughts"><summary>LLM reasoning (this step)</summary><pre>${esc(thoughts)}</pre></details>`;
}

function playerName(replay: any, i: number): string {
  const name = replay?.info?.TeamNames?.[i];
  const role = i === 0 ? 'Rule-maker' : `Scientist ${i}`;
  return name ? `${role} · ${esc(name)}` : role;
}

export function renderer(options: RendererOptions) {
  const { step, replay, parent } = options;
  const steps = (replay?.steps as any[]) ?? [];
  if (!steps.length) return;
  const current: any[] = steps[Math.min(Math.max(step ?? 0, 0), steps.length - 1)];
  const final: any[] = steps[steps.length - 1];
  const rm = current[0]?.observation ?? {};
  // The secret rule is only on the rule-maker's observation; scientists never see it.
  const rule = rm.secret_rule ?? final[0]?.observation?.secret_rule;
  const voided = current.some((p) => p?.status === 'ERROR' || p?.status === 'TIMEOUT');

  const ruleBlock = rule
    ? `<div class="rule"><div class="label">Secret rule ${rm.secret_rule ? '' : '(not chosen yet)'}</div>
        <div class="words">${esc(rule.words)}</div><code>${esc(rule.code)}</code>
        <div class="meta">${rule.source === 'library' ? 'Fallback library rule (rule-maker scores 0)' : 'Written by the rule-maker'} · accepts ${Math.round(rule.accept_rate * 100)}% of pairs</div></div>`
    : '<div class="rule"><em>The rule-maker is writing a rule…</em></div>';

  const attempts = (rm.rule_attempts ?? [])
    .map((a: any) => `<li><code>${esc(a.code)}</code> — ${esc(a.error)}</li>`)
    .join('');

  const scientists = current
    .slice(1)
    .map((agent, k) => {
      const i = k + 1;
      const o = agent?.observation ?? {};
      const mainline: MainlineEntry[] = o.mainline ?? [];
      const wrong: Guess[] = o.wrong_guesses ?? [];
      const status = o.solved ? 'Solved' : o.turns_used >= o.max_turns ? 'Out of turns' : 'Playing';
      const log = o.log ?? [];
      return `<section class="table">
        <header><h3>${playerName(replay, i)}</h3>
          <span class="status ${status.replace(/ /g, '-').toLowerCase()}">${status}</span>
          <span>Turns ${o.turns_used ?? 0}/${o.max_turns ?? '?'}</span>
          <span>Wrong guesses ${wrong.length}</span>
          <span>Score <b>${agent?.reward ?? 0}</b></span></header>
        <div class="event">${lastEventHtml(log[log.length - 1])}</div>
        <div class="mainline">${mainline.length ? mainlineHtml(mainline) : '<em>Waiting for the deal</em>'}</div>
        <div class="hand"><span class="label">Hand</span>${(o.hand ?? []).map((c: string) => cardHtml(c)).join('')}</div>
        ${wrong.length ? `<div class="wrong"><span class="label">Wrong guesses</span><ul>${wrong.map((g) => `<li>${esc(g.words)} <code>${esc(g.code)}</code>${g.error ? ` (${esc(g.error)})` : ''}</li>`).join('')}</ul></div>` : ''}
        ${thoughtsHtml(agent)}
      </section>`;
    })
    .join('');

  parent.innerHTML = `<div class="eleusis">
    ${voided ? '<div class="voided">Episode voided: an agent crashed or timed out. No result is recorded.</div>' : ''}
    <div class="top">
      <div><h2>Eleusis</h2><div class="phase">Phase: ${esc(rm.phase || 'setup')} · ${playerName(replay, 0)} reward <b>${current[0]?.reward ?? 0}</b></div></div>
      ${ruleBlock}
    </div>
    ${attempts ? `<div class="attempts"><span class="label">Rejected rules</span><ul>${attempts}</ul></div>` : ''}
    ${thoughtsHtml(current[0])}
    <div class="tables">${scientists}</div>
  </div>`;
}
