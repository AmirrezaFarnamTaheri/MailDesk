(() => {
  const HTML_EDIT_WARNING = 'HTML version removed because the plain-text message was edited during final review.';

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
  // audited resolution path. Resume/retry stays blocked server-side until one of
  // these choices is made after checking Gmail.
  toggleCampaignDetails = async function toggleCampaignDetailsWithResolution(card, id) {
    const existing = q('.queue-items', card);
    if (existing) {
      existing.remove();
      return;
    }
    try {
      const campaign = await api(`/api/campaigns/${id}`);
      const wrap = document.createElement('div');
      wrap.className = 'table-scroll queue-items';
      const table = document.createElement('table');
      table.className = 'data-table';
      table.innerHTML = '<thead><tr><th>#</th><th>Row</th><th>Recipient</th><th>Subject</th><th>Status</th><th>Attempts</th><th>Error</th><th>Review action</th></tr></thead>';
      const body = document.createElement('tbody');

      campaign.items.forEach(item => {
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
