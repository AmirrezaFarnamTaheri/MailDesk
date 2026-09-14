from __future__ import annotations

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, text: str) -> None:
    (ROOT / path).write_text(text, encoding="utf-8")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected 1 exact match, found {count}")
    return text.replace(old, new, 1)


def sub_once(text: str, pattern: str, replacement: str, label: str, flags: int = 0) -> str:
    output, count = re.subn(pattern, replacement, text, count=1, flags=flags)
    if count != 1:
        raise RuntimeError(f"{label}: expected 1 regex match, found {count}")
    return output


js = read("mailmerge_app/static/app.js")
js = js.replace("'templateSelect','templateName','templateTags','subjectTemplate'", "'templateSelect','templateName','subjectTemplate'")
js = js.replace("'browserSender','browserSenderSummary','verifySelectedBrowserButton','gmailAccount','throttleMs','scheduleAt','campaignName','skipDuplicates','refreshBeforeReview'", "'browserSender','browserSenderSummary','verifySelectedBrowserButton','gmailAccount','throttleMs','scheduleAt','campaignName','skipDuplicates'")
js = js.replace("'batchChip','finalSummary','reviewedCheck','sendConfirmation','confirmText','expectedConfirm','exportReviewButton','queueCampaignButton','backStepButton','nextStepButton'", "'finalSummary','exportReviewButton','queueCampaignButton','backStepButton','nextStepButton'")
js = js.replace("'campaignReadiness','reviewPosition'", "'reviewPosition'")
js = js.replace("'historyTable','refreshHistoryButton','firstRunDialog','finishOnboardingButton','snippetDialog'", "'historyTable','refreshHistoryButton','tourOverlay','tourProgress','tourTitle','tourText','tourSkipButton','tourBackButton','tourNextButton','snippetDialog'")
js = replace_once(js, "  campaigns: [], verifyingSenderId: '', sourceTab: 'file',\n", "  campaigns: [], verifyingSenderId: '', sourceTab: 'file', tourIndex: 0, tourActive: false,\n", "add tour state")
js = replace_once(js, "function clearApproval(){els.reviewedCheck.checked=false;els.confirmText.value='';}\n", "", "remove approval reset")

flow = '''function setStep(step){
  state.step=Math.min(4,Math.max(1,Number(step)));
  qsa('.workflow-step').forEach(b=>{
    const n=Number(b.dataset.step);
    b.classList.toggle('is-active',n===state.step);
    b.classList.toggle('is-complete',n<state.step);
    if(n===state.step)b.setAttribute('aria-current','step');else b.removeAttribute('aria-current');
  });
  qsa('.step-pane').forEach(p=>p.classList.toggle('is-visible',Number(p.dataset.stepPane)===state.step));
  els.backStepButton.disabled=state.step===1;
  els.nextStepButton.classList.toggle('is-hidden',state.step===4);
  const labels={1:'Continue to message',2:'Continue to check',3:'Continue to delivery'};
  els.nextStepButton.textContent=labels[state.step]||'Continue';
  if(state.step===4)updateFinalSummary();
}

async function advanceStep(){
  if(state.step===1){
    if(!state.importId){toast('Add recipients first','Choose a local file or load a Google Sheet.','error');return;}
    if(!els.toColumn.value){toast('Choose the email column','Select the spreadsheet column that contains recipient email addresses.','error');return;}
    setStep(2);return;
  }
  if(state.step===2){setStep(3);return;}
  if(state.step===3){
    if(!state.rendered||state.renderDirty)await renderCampaign(true);
    const rendered=state.rendered;
    if(!rendered||state.renderDirty)return;
    if(!rendered.total){toast('No recipients selected','Select at least one row before continuing.','error');return;}
    if(rendered.invalid){toast('Fix message errors first',`${rendered.invalid} message${rendered.invalid===1?' has':'s have'} blocking errors.`,'error',7000);return;}
    setStep(4);
  }
}

const TOUR_STEPS=[
  {step:1,selector:'.workflow-strip',title:'Four simple steps',text:'MailDesk moves from recipients to message, check, then delivery. You can come back to any step at any time.'},
  {step:1,selector:'[data-step-pane="1"] .panel',title:'Add recipients',text:'Drop in Excel or CSV, or load a Google Sheet. Choose the recipient email column; the rest is optional.'},
  {step:2,selector:'[data-step-pane="2"] .panel',title:'Write a reusable message',text:'Templates now keep message content only, so the same template works with different lists, senders and attachments.'},
  {step:3,selector:'[data-step-pane="3"] .panel',title:'Check the result',text:'Generate the personalized messages and fix any row with an error. Use the preview on the right to inspect individual messages.'},
  {step:4,selector:'[data-step-pane="4"] .panel',title:'Choose delivery',text:'Pick a dry run, browser compose, Gmail drafts or send. The final button tells you exactly what MailDesk will do.'},
];
function clearTourFocus(){qsa('.tour-focus').forEach(el=>el.classList.remove('tour-focus'));}
function showTourStep(index=state.tourIndex){
  state.tourIndex=Math.max(0,Math.min(TOUR_STEPS.length-1,index));
  const item=TOUR_STEPS[state.tourIndex];
  setStep(item.step);clearTourFocus();
  const target=q(item.selector);if(target){target.classList.add('tour-focus');target.scrollIntoView({block:'center',behavior:'smooth'});}
  els.tourProgress.textContent=`${state.tourIndex+1} of ${TOUR_STEPS.length}`;
  els.tourTitle.textContent=item.title;els.tourText.textContent=item.text;
  els.tourBackButton.disabled=state.tourIndex===0;
  els.tourNextButton.textContent=state.tourIndex===TOUR_STEPS.length-1?'Start MailDesk':'Next';
}
function startTour(){state.tourActive=true;els.tourOverlay.classList.remove('is-hidden');els.tourOverlay.setAttribute('aria-hidden','false');showTourStep(0);}
function finishTour(){
  localStorage.setItem('maildesk-tour-v1','1');state.tourActive=false;clearTourFocus();
  els.tourOverlay.classList.add('is-hidden');els.tourOverlay.setAttribute('aria-hidden','true');setStep(1);
}

function setSourceTab'''
js = sub_once(
    js,
    r"function setStep\(step\)\{.*?\nfunction setSourceTab",
    flow,
    "replace five-step flow and readiness with tour",
    re.S,
)

js = replace_once(
    js,
    "function loadTemplateIntoForm(){const t=state.templates.find(x=>x.id===els.templateSelect.value);if(!t)return;els.templateName.value=t.name||'';els.templateTags.value=t.tags||'';els.subjectTemplate.value=t.subject||'';els.bodyTemplate.value=t.body||'';els.bodyHtmlEditor.innerHTML=t.body_html||'';els.signatureHtmlEditor.innerHTML=t.signature_html||'';els.ccTemplate.value=t.cc_template||'';els.bccTemplate.value=t.bcc_template||'';state.selectedAttachmentIds=new Set(t.attachment_ids||[]);renderAttachments();if(t.default_account&&state.gmailAccounts.some(a=>a.email===t.default_account))els.gmailAccount.value=t.default_account;if(t.default_browser_sender_id&&state.browserSenders.some(s=>s.id===t.default_browser_sender_id))els.browserSender.value=t.default_browser_sender_id;scheduleRender();}\n",
    "function loadTemplateIntoForm(){const t=state.templates.find(x=>x.id===els.templateSelect.value);if(!t)return;els.templateName.value=t.name||'';els.subjectTemplate.value=t.subject||'';els.bodyTemplate.value=t.body||'';els.bodyHtmlEditor.innerHTML=t.body_html||'';els.signatureHtmlEditor.innerHTML=t.signature_html||'';els.ccTemplate.value=t.cc_template||'';els.bccTemplate.value=t.bcc_template||'';scheduleRender();}\n",
    "make template loading content-only",
)
js = replace_once(
    js,
    "function newTemplate(){const id=`template-${Date.now()}`;state.templates.push({id,name:'New template',subject:'',body:'',body_html:'',signature_html:'',cc_template:'',bcc_template:'',attachment_ids:[],tags:'',default_account:'',default_browser_sender_id:''});renderTemplateSelect();els.templateSelect.value=id;loadTemplateIntoForm();}\n",
    "function newTemplate(){const id=`template-${Date.now()}`;state.templates.push({id,name:'New template',subject:'',body:'',body_html:'',signature_html:'',cc_template:'',bcc_template:''});renderTemplateSelect();els.templateSelect.value=id;loadTemplateIntoForm();}\n",
    "simplify new template",
)
js = replace_once(
    js,
    "async function saveTemplate(){const id=els.templateSelect.value||`template-${Date.now()}`;const payload={id,name:els.templateName.value.trim()||'Untitled template',subject:els.subjectTemplate.value,body:els.bodyTemplate.value,body_html:els.bodyHtmlEditor.innerHTML,signature_html:els.signatureHtmlEditor.innerHTML,cc_template:els.ccTemplate.value,bcc_template:els.bccTemplate.value,attachment_ids:[...state.selectedAttachmentIds],tags:els.templateTags.value.trim(),default_account:els.gmailAccount.value||'',default_browser_sender_id:els.browserSender.value||''};const saved=await api(`/api/templates/${encodeURIComponent(id)}`,jsonOptions('PUT',payload));const idx=state.templates.findIndex(t=>t.id===id);if(idx>=0)state.templates[idx]=saved;else state.templates.push(saved);renderTemplateSelect();els.templateSelect.value=id;toast('Template saved',saved.name,'success');}\n",
    "async function saveTemplate(){const id=els.templateSelect.value||`template-${Date.now()}`;const payload={id,name:els.templateName.value.trim()||'Untitled template',subject:els.subjectTemplate.value,body:els.bodyTemplate.value,body_html:els.bodyHtmlEditor.innerHTML,signature_html:els.signatureHtmlEditor.innerHTML,cc_template:els.ccTemplate.value,bcc_template:els.bccTemplate.value};const saved=await api(`/api/templates/${encodeURIComponent(id)}`,jsonOptions('PUT',payload));const idx=state.templates.findIndex(t=>t.id===id);if(idx>=0)state.templates[idx]=saved;else state.templates.push(saved);renderTemplateSelect();els.templateSelect.value=id;toast('Template saved',saved.name,'success');}\n",
    "make template saving content-only",
)
js = replace_once(
    js,
    "selected_rows:state.selectedRows.size===state.allRowNumbers.length?[]:[...state.selectedRows]",
    "selected_rows:state.selectedRows.size===state.allRowNumbers.length?null:[...state.selectedRows]",
    "explicit all-row selection",
)
js = replace_once(js, "const selectedCount=state.selectedRows.size||state.allRowNumbers.length;", "const selectedCount=state.selectedRows.size;", "zero-row render count")

commit_edit = '''async function commitReviewEdit(){
  const m=state.rendered?.messages?.[state.messageIndex];if(!m)return;
  const previousBody=m.body;
  m.to=els.reviewTo.value.trim();m.cc=els.reviewCc.value.trim();m.bcc=els.reviewBcc.value.trim();m.subject=els.reviewSubject.value;m.body=els.reviewBody.value;
  const preserved=(m.errors||[]).filter(e=>!/^Recipient is blank\.$/.test(e)&&!/^Invalid (recipient|Cc|Bcc|address):/.test(e)&&e!=='Subject contains a line break.');m.errors=[...preserved];
  const invalid=[...splitAddressClient(m.to),...splitAddressClient(m.cc),...splitAddressClient(m.bcc)].filter(a=>!validEmailClient(a));
  if(!splitAddressClient(m.to).length)m.errors.push('Recipient is blank.');
  if(invalid.length)m.errors.push(`Invalid address: ${invalid.join(', ')}`);
  if(/\r|\n/.test(m.subject))m.errors.push('Subject contains a line break.');
  if(previousBody!==m.body&&m.body_html){m.body_html='';m.warnings=(m.warnings||[]).filter(w=>w!=='HTML version removed after plain-text edit.');m.warnings.push('HTML version removed after plain-text edit.');}
  state.rendered.invalid=state.rendered.messages.filter(x=>x.errors.length).length;state.rendered.valid=state.rendered.messages.length-state.rendered.invalid;state.renderDirty=true;
  const requestId=++state.batchRequestId;
  try{const result=await api('/api/batch-id',jsonOptions('POST',{messages:stripSources(state.rendered.messages)}));if(requestId!==state.batchRequestId)return;state.rendered.batch_id=result.batch_id;state.renderDirty=false;}
  catch(error){if(requestId===state.batchRequestId){state.renderDirty=true;toast('Could not update reviewed batch',error.message,'error');}}
  renderValidation();renderReview();updateFinalSummary();
}
'''
js = sub_once(js, r"async function commitReviewEdit\(\)\{.*?\n\}\nfunction splitAddressClient", commit_edit + "function splitAddressClient", "integrate review edit invariants", re.S)

final_flow = '''function updateModeUI(){const mode=currentMode();qsa('.mode-card').forEach(c=>c.classList.toggle('is-selected',q('input',c).checked));els.browserDelivery.classList.toggle('is-hidden',mode!=='browser');els.gmailDelivery.classList.toggle('is-hidden',!['draft','send'].includes(mode));updateBrowserSenderSummary();updateFinalSummary();}
function updateFinalSummary(){
  const r=state.rendered,mode=currentMode();
  const sender=mode==='browser'?(state.browserSenders.find(s=>s.id===els.browserSender.value)?.expected_email||'Choose a browser sender'):['draft','send'].includes(mode)?(els.gmailAccount.value||'Choose a Gmail sender'):'Not needed';
  const schedule=els.scheduleAt.value?new Date(els.scheduleAt.value).toLocaleString():'When queued';
  const labels={dry_run:'Dry run',browser:'Browser compose',draft:'Gmail drafts',send:'Send email'};
  els.finalSummary.innerHTML=`<div class="summary-card"><span>Messages</span><strong>${r?r.total:0}${state.renderDirty?' · needs re-check':''}</strong></div><div class="summary-card"><span>Action</span><strong>${labels[mode]}</strong></div><div class="summary-card"><span>Sender</span><strong>${esc(sender)}</strong></div><div class="summary-card"><span>Start</span><strong>${esc(schedule)}</strong></div>`;
  const okay=!!r&&!state.renderDirty&&r.total>0&&r.invalid===0&&(!['draft','send'].includes(mode)||!!els.gmailAccount.value)&&(mode!=='browser'||!!els.browserSender.value);
  const count=r?.total||0,plural=count===1?'message':'messages';
  let action=els.scheduleAt.value?`Schedule ${count} ${plural}`:mode==='dry_run'?`Run dry test · ${count}`:mode==='browser'?`Open ${count} browser draft${count===1?'':'s'}`:mode==='draft'?`Create ${count} Gmail draft${count===1?'':'s'}`:`Send ${count} ${plural}`;
  if(!r)action='Check messages before delivery';
  els.queueCampaignButton.disabled=!okay;els.queueCampaignButton.textContent=action;els.queueCampaignButton.classList.toggle('danger',mode==='send');
}
async function queueCampaign(){
  const r=state.rendered;if(!r||state.renderDirty){toast('Check messages again','The message batch changed since the last check.','error');return;}const mode=currentMode();
  let scheduled='';if(els.scheduleAt.value){const date=new Date(els.scheduleAt.value);if(Number.isNaN(date.getTime())){toast('Invalid schedule','Choose a valid date and time.','error');return;}scheduled=date.toISOString();}
  if(mode==='send'){
    const sender=els.gmailAccount.value||'the selected Gmail account';
    const verb=scheduled?'Schedule':'Send';
    if(!confirm(`${verb} ${r.total} email${r.total===1?'':'s'} from ${sender}?`))return;
  }
  const payload={name:els.campaignName.value.trim(),source_name:state.source?.filename||'',mode,account:els.gmailAccount.value||'',browser_sender_id:els.browserSender.value||'',batch_id:r.batch_id,messages:stripSources(r.messages),skip_duplicates:els.skipDuplicates.checked,throttle_ms:Number(els.throttleMs.value||0),scheduled_at:scheduled,confirm_send:mode==='send'};
  busy(true,scheduled?'Scheduling campaign…':'Queueing campaign…',`${r.total} messages`);
  try{const campaign=await api('/api/campaigns',jsonOptions('POST',payload));toast(scheduled?'Campaign scheduled':'Campaign queued',`${campaign.name} · ${campaign.status}`,'success',6500);setView('queue');await refreshQueue();}
  catch(error){toast('Campaign was not queued',error.message,'error',9000);}finally{busy(false);updateFinalSummary();}
}
function csvCell'''
js = sub_once(js, r"function updateModeUI\(\).*?\nfunction csvCell", final_flow, "simplify delivery and send confirmation", re.S)

accounts = '''function renderAccounts(){els.accountList.innerHTML='';state.gmailAccounts.forEach(a=>{const d=document.createElement('div');d.className='account-card';const problem=a.credential_error?`<div class="callout warning">${esc(a.credential_error)}</div>`:'';d.innerHTML=`<div class="account-avatar">${esc(a.email[0]?.toUpperCase()||'G')}</div><div class="account-main"><strong>${esc(a.email)}</strong><span>Updated ${new Date(a.updated_at).toLocaleString()}</span><div class="account-meta"><span class="pill ${a.gmail===true?'good':''}">Gmail</span><span class="pill ${a.sheets===true?'good':''}">Sheets</span></div>${problem}</div><button class="button ghost-danger small">Disconnect</button>`;q('button',d).addEventListener('click',()=>disconnectAccount(a.email));els.accountList.append(d);});if(!state.gmailAccounts.length)els.accountList.innerHTML='<div class="empty-card">No Google accounts connected yet.</div>';}
function renderBrowserProfiles'''
js = sub_once(js, r"function renderAccounts\(\).*?\nfunction renderBrowserProfiles", accounts, "integrate account errors", re.S)

js = js.replace("isSenderFresh", "isSenderVerified")
js = sub_once(js, r"function isSenderVerified\(s\)\{.*?\}\nfunction editBrowserSender", "function isSenderVerified(s){return !!s?.verified_at;}\nfunction editBrowserSender", "simplify browser verification age", re.S)
js = js.replace("Verified recently", "Verified").replace("Needs verification", "Verify route")
js = js.replace("verified recently", "verified").replace("verification required", "verify route")
js = js.replace(" · <span class=\"route-path\">/mail/u/${s.gmail_slot}/</span>", "")
js = js.replace("o.textContent=`${s.label} · ${s.expected_email} · /u/${s.gmail_slot}/`;", "o.textContent=`${s.label} · ${s.expected_email}`;")
js = js.replace(" · Gmail /u/${s.gmail_slot}/ · ${isSenderVerified(s)?'verified':'verify route'}", " · ${isSenderVerified(s)?'verified':'verify route'}")
js = js.replace("toast('Browser route saved',`Gmail /u/${payload.gmail_slot}/ → ${payload.expected_email}`,'success');", "toast('Browser route saved',payload.expected_email,'success');")
js = sub_once(js, r"async function startVerifyBrowserSender\(id\)\{.*?\}\nasync function confirmBrowserVerified", "async function startVerifyBrowserSender(id){state.verifyingSenderId=id;try{const result=await api(`/api/browser-senders/${encodeURIComponent(id)}/verify/open`,{method:'POST'});els.verifyBrowserText.innerHTML=`Check the Gmail window that opened and confirm it is signed in as <strong>${esc(result.expected_email)}</strong>.`;els.verifyBrowserDialog.showModal();}catch(error){state.verifyingSenderId='';toast('Could not open Gmail route',error.message,'error');}}\nasync function confirmBrowserVerified", "simplify browser verification prompt", re.S)
js = js.replace("toast('Browser route verified','This verification is valid for 30 minutes.','success');", "toast('Browser route verified','Verification will reset if you edit this route.','success');")

queue_detail = '''async function toggleCampaignDetails(card,id){
  const existing=q('.queue-items',card);if(existing){existing.remove();return;}
  try{
    const campaign=await api(`/api/campaigns/${encodeURIComponent(id)}/detail?limit=500&needs_review_limit=500`);
    const items=Array.isArray(campaign.items)?campaign.items:[];
    const wrap=document.createElement('div');wrap.className='table-scroll queue-items';
    if(Number(campaign.total||0)>items.length){const note=document.createElement('div');note.className='callout';note.textContent=`Showing ${items.length.toLocaleString()} of ${Number(campaign.total).toLocaleString()} rows. Items that need a decision are always included.`;wrap.append(note);}
    const table=document.createElement('table');table.className='data-table';table.innerHTML='<thead><tr><th>#</th><th>Row</th><th>Recipient</th><th>Subject</th><th>Status</th><th>Attempts</th><th>Error</th><th>Action</th></tr></thead>';
    const body=document.createElement('tbody');
    items.forEach(item=>{const tr=document.createElement('tr');[item.ordinal,item.row_number,item.recipient,item.subject,item.status,item.attempts,item.error||''].forEach(value=>{const td=document.createElement('td');td.textContent=value;td.title=value;tr.append(td);});const actions=document.createElement('td');if(item.status==='NeedsReview'){
      const done=document.createElement('button');done.type='button';done.className='button primary small';done.textContent=campaign.mode==='draft'?'Draft exists':'Sent';
      const notDone=document.createElement('button');notDone.type='button';notDone.className='button secondary small';notDone.textContent=campaign.mode==='draft'?'No draft':'Not sent';
      const resolve=async outcome=>{const completed=outcome==='resolve-sent';const wording=campaign.mode==='draft'?(completed?'a draft exists':'no draft was created'):(completed?'the message was sent':'the message was not sent');if(!confirm(`Confirm ${wording}?`))return;done.disabled=true;notDone.disabled=true;try{await api(`/api/campaigns/${encodeURIComponent(id)}/items/${item.id}/${outcome}`,{method:'POST'});await refreshQueue();}catch(error){toast('Could not resolve outcome',error.message,'error');done.disabled=false;notDone.disabled=false;}};
      done.addEventListener('click',()=>resolve('resolve-sent'));notDone.addEventListener('click',()=>resolve('resolve-not-sent'));const row=document.createElement('div');row.className='button-row';row.append(done,notDone);actions.append(row);
    }else actions.textContent='—';tr.append(actions);body.append(tr);});table.append(body);wrap.append(table);card.append(wrap);
  }catch(error){toast('Could not load campaign details',error.message,'error');}
}
async function queueAction'''
js = sub_once(js, r"async function toggleCampaignDetails\(card,id\).*?\nasync function queueAction", queue_detail, "integrate compact queue detail", re.S)
js = js.replace("setView('campaign');setStep(5);", "setView('campaign');setStep(4);")

js = sub_once(
    js,
    r"els\.browserSender\.addEventListener\('change'.*?els\.exportReviewButton\.addEventListener\('click',exportReviewCsv\);",
    "els.browserSender.addEventListener('change',()=>{updateBrowserSenderSummary();updateFinalSummary();});els.gmailAccount.addEventListener('change',updateFinalSummary);els.throttleMs.addEventListener('input',()=>{els.throttleMs.dataset.touched='1';});els.scheduleAt.addEventListener('change',updateFinalSummary);els.queueCampaignButton.addEventListener('click',queueCampaign);els.exportReviewButton.addEventListener('click',exportReviewCsv);",
    "simplify delivery bindings",
    re.S,
)
js = replace_once(
    js,
    "  els.finishOnboardingButton.addEventListener('click',()=>localStorage.setItem('maildesk-onboarded','1'));\n",
    "  els.tourSkipButton.addEventListener('click',finishTour);els.tourBackButton.addEventListener('click',()=>showTourStep(state.tourIndex-1));els.tourNextButton.addEventListener('click',()=>{if(state.tourIndex>=TOUR_STEPS.length-1)finishTour();else showTourStep(state.tourIndex+1);});\n",
    "wire tour controls",
)
js = replace_once(
    js,
    "async function init(){bindEvents();if(!localStorage.getItem('maildesk-onboarded')&&!localStorage.getItem('mailmerge-onboarded'))els.firstRunDialog.showModal();await checkHealth();try{await Promise.all([loadTemplates(),refreshAccountsAndBrowsers(),refreshQueue()]);}catch(error){toast('Initialization problem',error.message,'error');}restoreUiState();updateModeUI();if(!state.step)setStep(1);}\n",
    "async function init(){bindEvents();const firstRun=!localStorage.getItem('maildesk-tour-v1')&&!localStorage.getItem('maildesk-onboarded')&&!localStorage.getItem('mailmerge-onboarded');await checkHealth();try{await Promise.all([loadTemplates(),refreshAccountsAndBrowsers(),refreshQueue()]);}catch(error){toast('Initialization problem',error.message,'error');}restoreUiState();updateModeUI();setStep(1);if(firstRun)startTour();}\n",
    "start first-run tour after initialization",
)

# Remove obsolete approval calls left in unrelated paths.
js = js.replace("clearApproval();", "")
js = js.replace("updateReadiness();", "")
for forbidden in ("reviewedCheck", "confirmText", "expectedConfirm", "campaignReadiness", "refreshBeforeReview", "templateTags", "expectedConfirmation"):
    if forbidden in js:
        raise RuntimeError(f"obsolete frontend concept still present: {forbidden}")
write("mailmerge_app/static/app.js", js)

html = read("mailmerge_app/static/index.html")
html = html.replace("Personalized email, safely", "Personalized email")
html = html.replace("Add recipients, write the message, check every row, then choose how to deliver it.", "Add recipients, write your message, check the result, then choose delivery.")
start = html.index('        <div class="workflow-strip"')
end = html.index('        </div>', start) + len('        </div>')
workflow = '''        <div class="workflow-strip" role="tablist" aria-label="Campaign steps">
          <button type="button" class="workflow-step is-active" data-step="1"><span>1</span><b>Recipients</b><small>Choose audience</small></button>
          <button type="button" class="workflow-step" data-step="2"><span>2</span><b>Message</b><small>Write content</small></button>
          <button type="button" class="workflow-step" data-step="3"><span>3</span><b>Check</b><small>Preview rows</small></button>
          <button type="button" class="workflow-step" data-step="4"><span>4</span><b>Delivery</b><small>Choose & start</small></button>
        </div>'''
html = html[:start] + workflow + html[end:]
html = replace_once(
    html,
    '''                  <div class="field-grid three">
                    <label class="field"><span>Saved template</span><select id="templateSelect"></select></label>
                    <label class="field"><span>Template name</span><input id="templateName" type="text" maxlength="120"></label>
                    <label class="field"><span>Tags</span><input id="templateTags" type="text" placeholder="hiring, follow-up"></label>
                  </div>''',
    '''                  <div class="field-grid two">
                    <label class="field"><span>Saved template</span><select id="templateSelect"></select></label>
                    <label class="field"><span>Template name</span><input id="templateName" type="text" maxlength="120"></label>
                  </div>''',
    "remove template tags field",
)
html = html.replace("Write the email once, then use spreadsheet columns as placeholders for each recipient.", "Write a message once and reuse it with any recipient list or sender.")
html = html.replace('placeholder="Hello {{Name|there}}"', 'placeholder="Hello"')
html = html.replace('placeholder="Hello {{Name|there}},&#10;&#10;Write your message here."', 'placeholder="Write your message here."')

step4_start = html.index('            <section class="step-pane" data-step-pane="4">')
footer_start = html.index('            <div class="workflow-footer">', step4_start)
step4 = '''            <section class="step-pane" data-step-pane="4">
              <div class="panel final-panel">
                <div class="panel-head"><div><h2>Delivery</h2><p>Choose what should happen with the checked messages.</p></div></div>
                <div class="panel-body">
                  <div class="mode-grid" role="radiogroup" aria-label="Delivery mode">
                    <label class="mode-card is-selected"><input type="radio" name="mode" value="dry_run" checked><span class="mode-icon">◇</span><span><strong>Dry run</strong><small>Process locally without creating drafts or sending.</small></span></label>
                    <label class="mode-card"><input type="radio" name="mode" value="browser"><span class="mode-icon">◫</span><span><strong>Browser compose</strong><small>Open Gmail compose windows in a saved browser profile.</small></span></label>
                    <label class="mode-card"><input type="radio" name="mode" value="draft"><span class="mode-icon">□</span><span><strong>Gmail drafts</strong><small>Create drafts in the connected Gmail account.</small></span></label>
                    <label class="mode-card danger-mode"><input type="radio" name="mode" value="send"><span class="mode-icon">➤</span><span><strong>Send email</strong><small>Send through the connected Gmail account.</small></span></label>
                  </div>
                  <div id="browserDelivery" class="delivery-options is-hidden">
                    <label class="field"><span>Browser sender</span><select id="browserSender"></select></label>
                    <div class="sender-card" id="browserSenderSummary"><div class="sender-avatar">B</div><div><strong>No route selected</strong><span>Add a browser sender under Senders.</span></div><button class="button secondary small" id="verifySelectedBrowserButton">Verify</button></div>
                  </div>
                  <div id="gmailDelivery" class="delivery-options is-hidden">
                    <label class="field"><span>Gmail sender</span><select id="gmailAccount"></select></label>
                  </div>
                  <div class="field-grid two compact-top">
                    <label class="field"><span>Campaign name</span><input id="campaignName" type="text" placeholder="September outreach"></label>
                    <label class="field"><span>Schedule <em>optional</em></span><input id="scheduleAt" type="datetime-local"></label>
                  </div>
                  <details class="advanced compact-advanced">
                    <summary>More options</summary>
                    <div class="field-grid two">
                      <label class="field"><span>Delay between messages</span><div class="input-suffix"><input id="throttleMs" type="number" min="0" max="60000" value="750"><span>ms</span></div></label>
                      <label class="check-row"><input id="skipDuplicates" type="checkbox" checked><span>Skip messages that already completed successfully</span></label>
                    </div>
                  </details>
                  <div class="final-summary" id="finalSummary"></div>
                  <div class="final-actions"><button class="button secondary" id="exportReviewButton">Export review CSV</button><button class="button primary large" id="queueCampaignButton" disabled>Check messages before delivery</button></div>
                </div>
              </div>
            </section>

'''
html = html[:step4_start] + step4 + html[footer_start:]

ready_start = html.find('            <div class="readiness-card">')
if ready_start < 0:
    raise RuntimeError("readiness card not found")
review_start = html.index('            <div class="review-card">', ready_start)
html = html[:ready_start] + html[review_start:]

html = html.replace("Track work in progress, review uncertain outcomes, or retry only what needs attention.", "Track progress, inspect results and retry failed messages when needed.")
html = html.replace("Set conservative batch limits, default pacing and local backup behavior.", "Set the default batch size and pacing, or create a local backup.")
html = html.replace('<label class="field"><span>Gmail slot</span><input id="gmailSlot" type="number" min="0" max="99" value="0"></label>', '<label class="field"><span>Gmail account number</span><input id="gmailSlot" type="number" min="0" max="99" value="0"></label>')
html = html.replace('Example: slot 0 → <code>/mail/u/0/</code>, slot 1 → <code>/mail/u/1/</code>.', 'Use 0 for the first Gmail account in this browser profile, 1 for the second, and so on.')

old_dialog_start = html.index('  <dialog id="firstRunDialog"')
old_dialog_end = html.index('  <dialog id="snippetDialog"', old_dialog_start)
tour = '''  <div id="tourOverlay" class="tour-overlay is-hidden" aria-hidden="true">
    <div class="tour-card" role="dialog" aria-labelledby="tourTitle">
      <span class="tour-progress" id="tourProgress">1 of 5</span>
      <h2 id="tourTitle">Welcome to MailDesk</h2>
      <p id="tourText"></p>
      <div class="tour-actions"><button type="button" class="button ghost" id="tourSkipButton">Skip tour</button><div class="button-row"><button type="button" class="button secondary" id="tourBackButton">Back</button><button type="button" class="button primary" id="tourNextButton">Next</button></div></div>
    </div>
  </div>
'''
html = html[:old_dialog_start] + tour + html[old_dialog_end:]
html = html.replace("<div class=\"callout warning\">The browser will open the configured Gmail inbox. Confirm that the visible account is exactly the expected email before marking it verified.</div>", "<p>Confirm the account shown in the Gmail window. You only need to verify again if you edit this route.</p>")
html = html.replace('  <script src="/static/safety.js" defer></script>\n', '')
for forbidden in ('data-step="5"', 'data-step-pane="5"', 'id="campaignReadiness"', 'id="reviewedCheck"', 'id="confirmText"', 'id="templateTags"', 'id="firstRunDialog"', '/static/safety.js'):
    if forbidden in html:
        raise RuntimeError(f"obsolete UI still present: {forbidden}")
write("mailmerge_app/static/index.html", html)

css = read("mailmerge_app/static/app.css")
css = css.replace("repeat(5,1fr)", "repeat(4,1fr)").replace("repeat(5,minmax(120px,1fr))", "repeat(4,minmax(120px,1fr))")
css = re.sub(r"\.safety-gate\{[^}]*\}\.safety-gate code\{[^}]*\}", "", css)
css = re.sub(r"\.readiness-card\{.*?\.readiness-item small\{[^}]*\}\n", "", css, flags=re.S)
css += '''
.tour-overlay{position:fixed;inset:0;z-index:120;background:rgba(18,26,38,.24);pointer-events:none}
.tour-card{position:fixed;right:28px;bottom:28px;width:min(400px,calc(100vw - 40px));background:#fff;border:1px solid var(--line);border-radius:16px;box-shadow:0 24px 70px rgba(9,21,35,.24);padding:20px;pointer-events:auto}
.tour-progress{display:block;font-size:10px;font-weight:750;letter-spacing:.08em;text-transform:uppercase;color:var(--accent);margin-bottom:8px}.tour-card h2{font-size:18px;margin:0 0 7px}.tour-card p{font-size:12.5px;line-height:1.55;color:var(--muted);margin:0}.tour-actions{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-top:18px}
.tour-focus{position:relative;z-index:121!important;box-shadow:0 0 0 4px #fff,0 0 0 7px var(--accent)!important;border-radius:16px}
@media(max-width:820px){.tour-card{right:16px;bottom:16px;width:calc(100vw - 32px)}}
'''
write("mailmerge_app/static/app.css", css)

frontend_test = '''from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "mailmerge_app" / "static"
APP_JS = (STATIC / "app.js").read_text(encoding="utf-8")
INDEX_HTML = (STATIC / "index.html").read_text(encoding="utf-8")
APP_CSS = (STATIC / "app.css").read_text(encoding="utf-8")


class FrontendIntegrityTests(unittest.TestCase):
    def test_every_els_reference_is_registered_and_present_in_html(self):
        match = re.search(r"const ids\\s*=\\s*\\[(.*?)\\];", APP_JS, flags=re.S)
        self.assertIsNotNone(match)
        declared = set(re.findall(r"['\\\"]([A-Za-z][A-Za-z0-9_-]*)['\\\"]", match.group(1)))
        referenced = set(re.findall(r"\\bels\\.([A-Za-z_$][A-Za-z0-9_$]*)", APP_JS))
        html_ids = set(re.findall(r"\\bid=[\\\"']([^\\\"']+)[\\\"']", INDEX_HTML))
        self.assertEqual(sorted(referenced - declared), [])
        self.assertEqual(sorted(declared - html_ids), [])

    def test_frontend_has_one_code_path_instead_of_safety_monkey_patch(self):
        self.assertFalse((STATIC / "safety.js").exists())
        self.assertNotIn("/static/safety.js", INDEX_HTML)
        self.assertNotIn("baseRenderPayload", APP_JS)
        self.assertNotIn("baseCommitReviewEdit", APP_JS)

    def test_queue_gate_tracks_stale_render_state(self):
        self.assertIn("!state.renderDirty", APP_JS)
        self.assertIn("invalidateReview", APP_JS)
        self.assertIn("renderRequestId", APP_JS)

    def test_html_email_preview_blocks_remote_network_content(self):
        self.assertIn("Content-Security-Policy", APP_JS)
        self.assertIn("default-src 'none'", APP_JS)
        self.assertIn("connect-src 'none'", APP_JS)

    def test_row_selection_contract_distinguishes_all_from_none(self):
        self.assertIn("selected_rows:state.selectedRows.size===state.allRowNumbers.length?null:[...state.selectedRows]", APP_JS)
        self.assertNotIn("NO_ROWS_SENTINEL", APP_JS)

    def test_real_review_invariants_are_in_main_frontend(self):
        self.assertIn("Subject contains a line break.", APP_JS)
        self.assertIn("m.body_html=''", APP_JS)
        self.assertIn("/detail?limit=500&needs_review_limit=500", APP_JS)
        self.assertIn("resolve-sent", APP_JS)
        self.assertIn("resolve-not-sent", APP_JS)

    def test_campaign_flow_is_four_steps_without_redundant_approval_ritual(self):
        self.assertEqual(INDEX_HTML.count('class="workflow-step'), 4)
        self.assertNotIn('data-step="5"', INDEX_HTML)
        self.assertNotIn('campaignReadiness', APP_JS + INDEX_HTML)
        self.assertNotIn('reviewedCheck', APP_JS + INDEX_HTML)
        self.assertNotIn('expectedConfirmation', APP_JS)
        self.assertNotIn('refreshBeforeReview', APP_JS + INDEX_HTML)
        self.assertIn("Math.min(4", APP_JS)

    def test_first_run_tour_is_wired_end_to_end(self):
        for item in ('tourOverlay','tourProgress','tourTitle','tourText','tourSkipButton','tourBackButton','tourNextButton'):
            self.assertIn(f'id="{item}"', INDEX_HTML)
        self.assertIn("const TOUR_STEPS=[", APP_JS)
        self.assertIn("maildesk-tour-v1", APP_JS)
        self.assertIn("if(firstRun)startTour()", APP_JS)
        self.assertIn(".tour-focus", APP_CSS)

    def test_templates_are_content_focused(self):
        self.assertNotIn("templateTags", APP_JS + INDEX_HTML)
        self.assertNotIn("default_account", APP_JS)
        self.assertNotIn("default_browser_sender_id", APP_JS)
        match = re.search(r"async function saveTemplate\\(\\)\\{(.*?)\\nasync function deleteTemplate", APP_JS, re.S)
        self.assertIsNotNone(match)
        self.assertNotIn("attachment_ids", match.group(1))
        self.assertNotIn("gmailAccount", match.group(1))
        self.assertNotIn("browserSender", match.group(1))

    def test_send_confirmation_is_one_explicit_action(self):
        self.assertIn("confirm_send:mode==='send'", APP_JS)
        self.assertIn("if(!confirm(`${verb} ${r.total} email", APP_JS)
        self.assertNotIn("SEND ${r.messages.length}", APP_JS)

    def test_final_action_label_matches_delivery_mode(self):
        self.assertIn('Run dry test', APP_JS)
        self.assertIn('Open ${count} browser draft', APP_JS)
        self.assertIn('Create ${count} Gmail draft', APP_JS)
        self.assertIn('`Send ${count} ${plural}`', APP_JS)

    def test_optional_controls_stay_progressively_disclosed(self):
        self.assertIn('Optional: filter, sort or limit recipients', INDEX_HTML)
        self.assertIn('<summary>More options</summary>', INDEX_HTML)
        self.assertNotIn('<details class="advanced" open>', INDEX_HTML)


if __name__ == "__main__":
    unittest.main()
'''
write("tests/test_frontend_integrity.py", frontend_test)
print("frontend simplification and tour applied")
