(() => {
  const HTML_EDIT_WARNING = 'HTML version removed because the plain-text message was edited during final review.';
  const NO_ROWS_SENTINEL = '__maildesk_no_rows_selected__';
  const QUEUE_DETAIL_ROW_LIMIT = 500;

  // Keep final-review validation aligned with the backend's conservative email
  // rules. The original browser regex accepted invalid hostnames such as domains
  // containing underscores, so a row could look valid until the server rejected
  // the campaign. The server remains authoritative; this prevents misleading UI.
  validEmailClient = function validEmailClientStrict(value) {
    const address = String(value || '');
    if (!address || address.length > 254 || /\s/.test(address)) return false;
    const at = address.indexOf('@');
    if (at <= 0 || at !== address.lastIndexOf('@')) return false;
    const local = address.slice(0, at);
    const domain = address.slice(at + 1);
    const localAtom = /^[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+(?:\.[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+)*$/;
    if (!localAtom.test(local) || new TextEncoder().encode(local).length > 64) return false;
    if (!domain.includes('.') || domain.startsWith('.') || domain.endsWith('.')) return false;
    if (/[\/@:#?\\]/.test(domain)) return false;
    let asciiDomain = '';
    try {
      const parsed = new URL(`http://${domain}`);
      if (parsed.username || parsed.password || parsed.port || parsed.pathname !== '/' || parsed.search || parsed.hash) return false;
      asciiDomain = parsed.hostname;
    } catch {
      return false;
    }
    if (!asciiDomain || asciiDomain.length > 253) return false;
    const label = /^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$/;
    return asciiDomain.split('.').every(part => label.test(part));
  };

  // The backend intentionally treats selected_rows=[] as "all rows" so callers
  // can omit a large all-row list. The UI, however, also reaches size=0 when the
  // user explicitly deselects every row. Encode that second state with an
  // impossible spreadsheet row sentinel so "select nobody" can never become
  // "process everybody".
  const baseRenderPayload = renderPayload;
  renderPayload = function renderPayloadWithExplicitEmptySelection() {
    const payload = baseRenderPayload();
    if (state.allRowNumbers.length > 0 && state.selectedRows.size === 0) {
      payload.selected_rows = [NO_ROWS_SENTINEL];
    }
    return payload;
  };

  // Final-review plain-text edits must not leave an older HTML alternative in the
  // MIME message. Mail clients commonly prefer HTML, so keeping stale HTML would
  // make the delivered content differ from what the reviewer just changed.
  els.reviewBody.addEventListener('input', () => {
    const message = state.rendered?.messages?.[state.messageIndex];
    if (!message?.body_html) return;
    message.body_html = '';
    message.warnings ||= [];
    if (!message.warnings.includes(HTML_EDIT_WARNING)) message.warnings.push(HTML_EDIT_WARNING);
    state.renderDirty = true;
    clearApproval();
    els.htmlPreviewWrap.classList.add('is-hidden');
    els.htmlPreview.removeAttribute('srcdoc');
    renderValidation();
    updateFinalSummary();
  });

  // Keep corrupt local credentials visible instead of letting one account make
  // the whole Accounts page unusable. The backend marks these records so the user
  // can disconnect and reconnect them safely.
  renderAccounts = function renderAccountsWithCredentialErrors() {
    els.accountList.innerHTML = '';
    state.gmailAccounts.forEach(account => {
      const card = document.createElement('div');
      card.className = 'account-card';
      const problem = account.credential_error
        ? `<div class="callout warning">${esc(account.credential_error)}</div>`
        : '';
      card.innerHTML = `<div class="account-avatar">${esc(account.email[0]?.toUpperCase() || 'G')}</div><div class="account-main"><strong>${esc(account.email)}</strong><span>Updated ${new Date(account.updated_at).toLocaleString()}</span><div class="account-meta"><span class="pill ${account.gmail === true ? 'good' : ''}">Gmail compose</span><span class="pill ${account.sheets === true ? 'good' : ''}">Sheets read-only</span></div>${problem}</div><button class="button ghost-danger small">Disconnect</button>`;
      q('button', card).addEventListener('click', () => disconnectAccount(account.email));
      els.accountList.append(card);
    });
    if (!state.gmailAccounts.length) els.accountList.innerHTML = '<div class="empty-card">No Google accounts connected yet.</div>';
  };

  // Replace the queue detail renderer so uncertain Gmail outcomes have an explicit
  // audited resolution path. Large campaigns are deliberately not expanded into
  // thousands of DOM rows at once: that can freeze the desktop WebView. Always
  // include NeedsReview rows even when they fall outside the normal detail window.
  toggleCampaignDetails = async function toggleCampaignDetailsWithResolution(card, id) {
    const existing = q('.queue-items', card);
    if (existing) {
      existing.remove();
      return;
    }
    try {
      const campaign = await api(`/api/campaigns/${id}`);
      const allItems = Array.isArray(campaign.items) ? campaign.items : [];
      const normalItems = allItems.slice(0, QUEUE_DETAIL_ROW_LIMIT);
      const includedIds = new Set(normalItems.map(item => item.id));
      const reviewItems = allItems.filter(item => item.status === 'NeedsReview' && !includedIds.has(item.id));
      const visibleItems = [...normalItems, ...reviewItems];

      const wrap = document.createElement('div');
      wrap.className = 'table-scroll queue-items';
      if (allItems.length > visibleItems.length) {
        const notice = document.createElement('div');
        notice.className = 'callout';
        notice.textContent = `Showing ${visibleItems.length.toLocaleString()} of ${allItems.length.toLocaleString()} items to keep this view responsive. Safety-review items are always included.`;
        wrap.append(notice);
      }

      const table = document.createElement('table');
      table.className = 'data-table';
      table.innerHTML = '<thead><tr><th>#</th><th>Row</th><th>Recipient</th><th>Subject</th><th>Status</th><th>Attempts</th><th>Error</th><th>Review action</th></tr></thead>';
      const body = document.createElement('tbody');

      visibleItems.forEach(item => {
        const tr = document.createElement('tr');
        [item.ordinal, item.row_number, item.recipient, item.subject, item.status, item.attempts, item.error || ''].forEach(value => {
          const td = document.createElement('td');
          td.textContent = value;
          td.title = value;
          tr.append(td);
        });

        const actions = document.createElement('td');
        if (item.status === 'NeedsReview') {
          const completed = document.createElement('button');
          completed.type = 'button';
          completed.className = 'button primary small';
          completed.textContent = campaign.mode === 'draft' ? 'Draft exists' : 'Sent';
          completed.title = 'Use only after checking Gmail and confirming the operation completed.';

          const notCompleted = document.createElement('button');
          notCompleted.type = 'button';
          notCompleted.className = 'button secondary small';
          notCompleted.textContent = campaign.mode === 'draft' ? 'No draft' : 'Not sent';
          notCompleted.title = 'Use only after checking Gmail and confirming the operation did not complete.';

          const resolve = async (outcome) => {
            const completedOutcome = outcome === 'resolve-sent';
            const wording = campaign.mode === 'draft'
              ? (completedOutcome ? 'a draft exists' : 'no draft was created')
              : (completedOutcome ? 'the message was sent' : 'the message was not sent');
            if (!confirm(`Confirm that you checked Gmail and ${wording}? This decision is written to history.`)) return;
            completed.disabled = true;
            notCompleted.disabled = true;
            try {
              await api(`/api/campaigns/${encodeURIComponent(id)}/items/${item.id}/${outcome}`, {method: 'POST'});
              toast('Uncertain outcome resolved', wording, 'success', 7000);
              await refreshQueue();
            } catch (error) {
              toast('Could not resolve outcome', error.message, 'error', 8000);
              completed.disabled = false;
              notCompleted.disabled = false;
            }
          };

          completed.addEventListener('click', () => resolve('resolve-sent'));
          notCompleted.addEventListener('click', () => resolve('resolve-not-sent'));
          const row = document.createElement('div');
          row.className = 'button-row';
          row.append(completed, notCompleted);
          actions.append(row);
        } else {
          actions.textContent = '—';
        }
        tr.append(actions);
        body.append(tr);
      });
      table.append(body);
      wrap.append(table);
      card.append(wrap);
    } catch (error) {
      toast('Could not load campaign details', error.message, 'error');
    }
  };
})();
