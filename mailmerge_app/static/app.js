const q = (s, root = document) => root.querySelector(s);
const qsa = (s, root = document) => [...root.querySelectorAll(s)];
const els = {};
const ids = [
  'viewTitle','viewSubtitle','queueBadge','versionLabel','startTourButton',
  'sheetFile','dropzone','sheetFileLabel','googleSheetAccount','googleSheetUrl','loadGoogleSheetButton','refreshGoogleSheetButton','snapshotHint','sourceState',
  'sheetSelect','headerRow','toColumn','nameColumn','ccColumn','bccColumn','filterColumn','filterOperator','filterValue','sortColumn','sortDirection','rowLimit','trimValues','mappingCallout','sheetPreviewWrap','sheetSummary','selectionSummary','sheetPreview','selectVisibleButton','clearVisibleButton',
  'templateSelect','templateName','subjectTemplate','bodyTemplate','bodyHtmlEditor','signatureHtmlEditor','placeholderList','placeholderMappingList','autoMapPlaceholdersButton','snippetList','attachmentList','attachmentFile','newSnippetButton','newTemplateButton','saveTemplateButton','deleteTemplateButton','clearFormattingButton',
  'ccTemplate','bccTemplate','attachmentColumn','renderButton','validationSummary','validationList',
  'browserDelivery','gmailDelivery','browserSender','browserSenderSummary','verifySelectedBrowserButton','gmailAccount','throttleMs','scheduleAt','campaignName','skipDuplicates',
  'finalSummary','sendConfirmation','confirmText','expectedConfirm','exportReviewButton','queueCampaignButton','backStepButton','nextStepButton',
  'reviewPosition','prevMessage','nextMessage','reviewEmpty','reviewContent','reviewStatus','reviewTo','reviewCc','reviewBcc','reviewSubject','reviewBody','htmlPreviewWrap','htmlPreview','reviewMeta','liveSheetCard','liveSheetSummary','liveSheetEmpty','liveSheetScroll','liveSheetTable',
  'queueList','refreshQueueButton','oauthFile','includeSheetsScope','accountList','newBrowserSenderButton','browserRouteForm','browserSenderId','browserSenderLabel','browserProfile','gmailSlot','browserExpectedEmail','profileEmails','detectedBrowserAccounts','browserDetectionHint','rescanBrowserProfilesButton','manualBrowserSenderOptions','saveBrowserSenderButton','browserSenderList','maxBatchSize','defaultThrottle','saveSettingsButton','backupButton',
  'historyTable','refreshHistoryButton','snippetDialog','snippetName','snippetContent','saveSnippetDialogButton','verifyBrowserDialog','verifyBrowserText','confirmBrowserVerifiedButton',
  'tourOverlay','tourSpotlight','tourCard','tourStepLabel','tourTitle','tourText','skipTourButton','tourBackButton','tourNextButton',
  'toastStack','busyOverlay','busyTitle','busyDetail'
];
ids.forEach(id => els[id] = document.getElementById(id));

const AUTO_RENDER_ROW_LIMIT = 1000;
const QUEUE_DETAIL_ROW_LIMIT = 500;
const SUBJECT_LINE_ERROR = 'Subject contains a line break.';
const HTML_EDIT_WARNING = 'HTML version removed after editing the plain-text message.';
const TOUR_STORAGE_KEY = 'maildesk-tour-seen-v1';
const state = {
  view: 'campaign', step: 1,
  importId: '', source: null, headers: [], previewRows: [], allRowNumbers: [], selectedRows: new Set(), rowOverrides: {}, suggestions: {}, placeholderMappings: {}, liveSheetRow: '',
  templates: [], snippets: [], attachments: [], selectedAttachmentIds: new Set(), activeEditor: null,
  gmailAccounts: [], browserProfiles: [], browserSenders: [], settings: {max_batch_size:500, default_throttle_ms:750},
  rendered: null, messageIndex: 0, renderTimer: null, renderRequestId: 0, renderRevision: 0, batchRequestId: 0, renderDirty: true,
  campaigns: [], verifyingSenderId: '', sourceTab: 'file', tourIndex: 0, tourPreviousFocus: null,
};

const titles = {
  campaign: ['Compose campaign', 'Add recipients, write the message, check it, then choose how to deliver it.'],
  queue: ['Campaign queue', 'Track queued, running and completed campaigns.'],
  accounts: ['Senders & settings', 'Connect Gmail or add a browser sender.'],
  history: ['Activity history', 'See the result of each campaign action.'],
};

async function api(url, options = {}) {
  const response = await fetch(url, options);
  const type = response.headers.get('content-type') || '';
  const payload = type.includes('application/json') ? await response.json() : await response.text();
  if (!response.ok) throw new Error(payload?.detail || payload || `HTTP ${response.status}`);
  return payload;
}
function jsonOptions(method, body) { return {method, headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)}; }
function busy(on, title='Working…', detail='') { els.busyOverlay.classList.toggle('is-hidden', !on); els.busyTitle.textContent=title; els.busyDetail.textContent=detail; }
function toast(title, message='', kind='info', duration=4500) {
  const item=document.createElement('div'); item.className=`toast ${kind==='error'?'error':kind==='success'?'success':''}`;
  const strong=document.createElement('strong'); strong.textContent=title; const span=document.createElement('span'); span.textContent=message; item.append(strong,span); els.toastStack.append(item); setTimeout(()=>item.remove(),duration);
}
function esc(value=''){ return String(value).replace(/[&<>"']/g,ch=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch])); }
function currentMode(){ return q('input[name="mode"]:checked')?.value || 'dry_run'; }
function clearConfirmation(){els.confirmText.value='';}
function invalidateReview({clearRendered=false}={}){
  state.renderRevision += 1;
  state.renderDirty = true;
  state.renderRequestId += 1;
  clearConfirmation();
  if(clearRendered){state.rendered=null;state.messageIndex=0;renderValidation();renderReview();}
  updateFinalSummary();
}

function setView(view){
  state.view=view; qsa('.nav-item').forEach(b=>b.classList.toggle('is-active',b.dataset.view===view));
  qsa('.view').forEach(v=>v.classList.remove('is-visible')); document.getElementById(`${view}View`).classList.add('is-visible');
  [els.viewTitle.textContent, els.viewSubtitle.textContent]=titles[view];
  document.title=view==='campaign'?'MailDesk':`MailDesk — ${titles[view][0]}`;
  if(view==='queue') refreshQueue(); if(view==='history') refreshHistory(); if(view==='accounts') refreshAccountsAndBrowsers();
}
function setStep(step){
  state.step=Math.min(5,Math.max(1,Number(step)));
  qsa('.workflow-step').forEach(b=>{
    const n=Number(b.dataset.step);
    b.classList.toggle('is-active',n===state.step);
    b.classList.toggle('is-complete',n<state.step);
    if(n===state.step)b.setAttribute('aria-current','step');else b.removeAttribute('aria-current');
  });
  qsa('.step-pane').forEach(p=>p.classList.toggle('is-visible',Number(p.dataset.stepPane)===state.step));
  els.backStepButton.disabled=state.step===1;
  els.nextStepButton.classList.toggle('is-hidden',state.step===5);
  const labels={1:'Continue to message',2:'Continue to check',3:'Continue to delivery',4:'Review campaign'};
  els.nextStepButton.textContent=labels[state.step]||'Continue';
  if(state.step===5) updateFinalSummary();
}

async function advanceStep(){
  if(state.step===1){
    if(!state.importId){toast('Add recipients first','Choose a local file or load a Google Sheet snapshot.','error');return;}
    if(!els.toColumn.value){toast('Choose the email column','Select which spreadsheet column contains recipient email addresses.','error');return;}
    setStep(2);return;
  }
  if(state.step===2){setStep(3);return;}
  if(state.step===3){
    if(!state.rendered||state.renderDirty)await renderCampaign(true);
    const rendered=state.rendered;
    if(!rendered||state.renderDirty)return;
    if(!rendered.total){toast('No recipients selected','Adjust the selection or filter before continuing.','error');return;}
    if(rendered.invalid){toast('Fix message errors first',`${rendered.invalid} message${rendered.invalid===1?' has':'s have'} blocking errors.`,'error',7000);return;}
    setStep(4);return;
  }
  if(state.step===4){
    const mode=currentMode();
    if(mode==='browser'&&!els.browserSender.value){toast('Choose a browser sender','Select a browser sender before review.','error');return;}
    if(['draft','send'].includes(mode)&&!els.gmailAccount.value){toast('Choose a Gmail sender','Select a connected Google account before review.','error');return;}
    setStep(5);
  }
}


function setSourceTab(tab){ state.sourceTab=tab; qsa('.source-tab').forEach(b=>b.classList.toggle('is-active',b.dataset.sourceTab===tab)); qsa('.source-pane').forEach(p=>p.classList.remove('is-visible')); document.getElementById(tab==='file'?'fileSourcePane':'googleSourcePane').classList.add('is-visible'); }
function setEditorTab(tab){ qsa('.editor-tab').forEach(b=>b.classList.toggle('is-active',b.dataset.editor===tab)); qsa('.editor-pane').forEach(p=>p.classList.remove('is-visible')); document.getElementById(tab==='plain'?'plainEditorPane':'htmlEditorPane').classList.add('is-visible'); }

async function uploadSheet(file){
  if(!file)return; busy(true,'Reading spreadsheet…',file.name); const form=new FormData();form.append('file',file);
  try{ const result=await api('/api/imports',{method:'POST',body:form}); await applyImport(result); toast('Spreadsheet loaded',`${result.sheets.length} worksheet${result.sheets.length===1?'':'s'} available.`,'success'); }
  catch(error){toast('Could not load spreadsheet',error.message,'error');} finally{busy(false);els.sheetFile.value='';}
}
async function loadGoogleSheet(){
  const account=els.googleSheetAccount.value, spreadsheet=els.googleSheetUrl.value.trim(); if(!account||!spreadsheet){toast('Google Sheet details needed','Select an account with Sheets access and paste a Sheet URL or ID.','error');return;}
  busy(true,'Loading Google Sheet…','Creating a local snapshot.');
  try{ const result=await api('/api/imports/google-sheet',jsonOptions('POST',{account,spreadsheet})); await applyImport(result); setSourceTab('google'); toast('Google Sheet loaded',`Snapshot created at ${new Date(result.snapshot_at).toLocaleString()}.`,'success'); }
  catch(error){toast('Could not load Google Sheet',error.message,'error',8000);} finally{busy(false);}
}
async function refreshGoogleSheet(){
  if(!state.importId||state.source?.source_type!=='google_sheet')return; busy(true,'Refreshing Google Sheet…','Replacing the local snapshot.');
  try{
    const result=await api(`/api/imports/${state.importId}/refresh`,{method:'POST'});
    state.source=result; state.rowOverrides={}; invalidateReview({clearRendered:true}); await loadSheetPreview(true);
    toast('Snapshot refreshed','Row edits were cleared. Check the refreshed messages before queueing.','success');
  }
  catch(error){toast('Refresh failed',error.message,'error');} finally{busy(false);}
}
async function applyImport(result){
  clearTimeout(state.renderTimer); state.importId=result.import_id; state.source=result; state.rowOverrides={}; state.selectedRows=new Set(); state.headers=[]; state.previewRows=[]; state.allRowNumbers=[]; state.placeholderMappings={}; state.liveSheetRow=''; invalidateReview({clearRendered:true});
  els.sourceState.textContent=result.source_type==='google_sheet'?'Google snapshot':'Local file'; els.sheetFileLabel.textContent=result.filename;
  els.sheetSelect.innerHTML=''; (result.sheets||[]).forEach(name=>{const o=document.createElement('option');o.value=name;o.textContent=name;els.sheetSelect.append(o);}); els.sheetSelect.disabled=false;els.headerRow.disabled=false;els.headerRow.value='';
  els.refreshGoogleSheetButton.classList.toggle('is-hidden',result.source_type!=='google_sheet'); els.snapshotHint.textContent=result.snapshot_at?`Snapshot: ${new Date(result.snapshot_at).toLocaleString()}`:'';
  await loadSheetPreview(true);
}
function populateSelect(select, headers, blank='— Not mapped —'){
  const prev=select.value;select.innerHTML='';if(blank!==null){const o=document.createElement('option');o.value='';o.textContent=blank;select.append(o);} headers.forEach(h=>{const o=document.createElement('option');o.value=h;o.textContent=h;select.append(o);}); if(headers.includes(prev))select.value=prev;select.disabled=false;
}
async function loadSheetPreview(resetSelection=false){
  if(!state.importId||!els.sheetSelect.value)return; const params=new URLSearchParams({sheet:els.sheetSelect.value});if(els.headerRow.value)params.set('header_row',els.headerRow.value);
  try{ const result=await api(`/api/imports/${state.importId}/preview?${params}`); state.headers=result.headers;state.previewRows=result.rows;state.allRowNumbers=result.row_numbers||result.rows.map(r=>r._row);state.suggestions=result.suggestions||{};state.source=result.source||state.source;els.headerRow.value=result.header_row;
    [els.toColumn,els.nameColumn,els.ccColumn,els.bccColumn,els.filterColumn,els.sortColumn,els.attachmentColumn].forEach(s=>populateSelect(s,result.headers,s===els.toColumn?'Select email column':'— Not mapped —'));
    if(resetSelection){state.selectedRows=new Set(state.allRowNumbers);state.rowOverrides={};}
    const sug=state.suggestions; if(sug.to&&result.headers.includes(sug.to))els.toColumn.value=sug.to;if(sug.name&&result.headers.includes(sug.name))els.nameColumn.value=sug.name;if(sug.cc&&result.headers.includes(sug.cc))els.ccColumn.value=sug.cc;if(sug.bcc&&result.headers.includes(sug.bcc))els.bccColumn.value=sug.bcc;if(sug.attachment&&result.headers.includes(sug.attachment))els.attachmentColumn.value=sug.attachment;if(sug.status&&result.headers.includes(sug.status))els.filterColumn.value=sug.status;
    els.filterValue.disabled=!els.filterColumn.value||els.filterOperator.value==='not_empty'; els.mappingCallout.textContent=`Suggested mapping: recipient ${sug.to||'not detected'}${sug.name?` · name ${sug.name}`:''}${sug.status?` · filter ${sug.status}`:''}. Review before continuing.`;
    renderSheetPreview();renderPlaceholders();els.sheetPreviewWrap.classList.remove('is-hidden');els.sheetSummary.textContent=`${result.total_rows} data row${result.total_rows===1?'':'s'}`;updateSelectionSummary(); scheduleRender();
  }catch(error){invalidateReview();toast('Could not preview source',error.message,'error');}
}
function renderSheetPreview(){
  els.sheetPreview.innerHTML=''; const thead=document.createElement('thead'),tr=document.createElement('tr'); const sel=document.createElement('th');sel.className='row-select';sel.textContent='✓';tr.append(sel);const rn=document.createElement('th');rn.textContent='Row';tr.append(rn);state.headers.forEach(h=>{const th=document.createElement('th');th.textContent=h;tr.append(th);});thead.append(tr);els.sheetPreview.append(thead);const tbody=document.createElement('tbody');
  state.previewRows.forEach(row=>{const tr=document.createElement('tr');const tdSel=document.createElement('td');tdSel.className='row-select';const cb=document.createElement('input');cb.type='checkbox';cb.checked=state.selectedRows.has(row._row);cb.addEventListener('change',()=>{cb.checked?state.selectedRows.add(row._row):state.selectedRows.delete(row._row);updateSelectionSummary();scheduleRender();});tdSel.append(cb);tr.append(tdSel);const tdRow=document.createElement('td');tdRow.className='row-number';tdRow.textContent=row._row;tr.append(tdRow);state.headers.forEach(h=>{const td=document.createElement('td');const overridden=state.rowOverrides[row._row]?.[h];td.textContent=overridden!==undefined?overridden:(row[h]||'');td.title='Double-click or type to edit this value for this campaign only.';td.contentEditable='true';td.spellcheck=false;td.addEventListener('input',()=>{state.rowOverrides[row._row] ||= {};state.rowOverrides[row._row][h]=td.textContent;scheduleRender();});tr.append(td);});tbody.append(tr);});els.sheetPreview.append(tbody);
}
function updateSelectionSummary(){els.selectionSummary.textContent=state.selectedRows.size===state.allRowNumbers.length?' · all selected':` · ${state.selectedRows.size} selected`;}
function renderLiveSheet(){
  if(!state.previewRows.length||!state.headers.length){els.liveSheetSummary.textContent='No spreadsheet loaded';els.liveSheetEmpty.classList.remove('is-hidden');els.liveSheetScroll.classList.add('is-hidden');els.liveSheetTable.innerHTML='';return;}
  const currentRendered=state.rendered?.messages?.[state.messageIndex];const activeRow=String(state.liveSheetRow||currentRendered?.row_number||state.previewRows[0]._row||'');state.liveSheetSummary.textContent=`${state.source?.filename||'Spreadsheet'} · ${state.previewRows.length}${state.allRowNumbers.length>state.previewRows.length?` of ${state.allRowNumbers.length}`:''} rows shown`;els.liveSheetEmpty.classList.add('is-hidden');els.liveSheetScroll.classList.remove('is-hidden');els.liveSheetTable.innerHTML='';
  const thead=document.createElement('thead'),head=document.createElement('tr');['Row',...state.headers].forEach(label=>{const th=document.createElement('th');th.textContent=label;head.append(th);});thead.append(head);els.liveSheetTable.append(thead);const tbody=document.createElement('tbody');state.previewRows.forEach(row=>{const tr=document.createElement('tr');tr.dataset.row=String(row._row);tr.classList.toggle('is-active',String(row._row)===activeRow);const rowCell=document.createElement('td');rowCell.textContent=row._row;tr.append(rowCell);state.headers.forEach(header=>{const td=document.createElement('td');td.textContent=sourceCell(row,header);td.title=td.textContent;tr.append(td);});tr.addEventListener('click',()=>{state.liveSheetRow=String(row._row);const index=state.rendered?.messages?.findIndex(message=>String(message.row_number)===String(row._row))??-1;if(index>=0){state.messageIndex=index;renderReview();}else{renderLiveSheet();renderPlaceholderMappings();}});tbody.append(tr);});els.liveSheetTable.append(tbody);
}

async function loadTemplates(){ state.templates=await api('/api/templates'); state.snippets=await api('/api/snippets'); state.attachments=await api('/api/attachments'); renderTemplateSelect(); renderSnippets();renderAttachments(); }
function renderTemplateSelect(){const prev=els.templateSelect.value;els.templateSelect.innerHTML='';state.templates.forEach(t=>{const o=document.createElement('option');o.value=t.id;o.textContent=t.name;els.templateSelect.append(o);});if(state.templates.some(t=>t.id===prev))els.templateSelect.value=prev;else if(state.templates[0])els.templateSelect.value=state.templates[0].id;loadTemplateIntoForm();}
function loadTemplateIntoForm(){const t=state.templates.find(x=>x.id===els.templateSelect.value);if(!t)return;els.templateName.value=t.name||'';els.subjectTemplate.value=t.subject||'';els.bodyTemplate.value=t.body||'';els.bodyHtmlEditor.innerHTML=t.body_html||'';els.signatureHtmlEditor.innerHTML=t.signature_html||'';els.ccTemplate.value=t.cc_template||'';els.bccTemplate.value=t.bcc_template||'';state.selectedAttachmentIds=new Set(t.attachment_ids||[]);renderAttachments();if(t.default_account&&state.gmailAccounts.some(a=>a.email===t.default_account))els.gmailAccount.value=t.default_account;if(t.default_browser_sender_id&&state.browserSenders.some(s=>s.id===t.default_browser_sender_id))els.browserSender.value=t.default_browser_sender_id;scheduleRender();}
function newTemplate(){const id=`template-${Date.now()}`;state.templates.push({id,name:'New template',subject:'',body:'',body_html:'',signature_html:'',cc_template:'',bcc_template:'',attachment_ids:[],tags:'',default_account:'',default_browser_sender_id:''});renderTemplateSelect();els.templateSelect.value=id;loadTemplateIntoForm();}
async function saveTemplate(){const id=els.templateSelect.value||`template-${Date.now()}`;const payload={id,name:els.templateName.value.trim()||'Untitled template',subject:els.subjectTemplate.value,body:els.bodyTemplate.value,body_html:els.bodyHtmlEditor.innerHTML,signature_html:els.signatureHtmlEditor.innerHTML,cc_template:els.ccTemplate.value,bcc_template:els.bccTemplate.value,attachment_ids:[...state.selectedAttachmentIds],tags:(state.templates.find(t=>t.id===id)?.tags||''),default_account:els.gmailAccount.value||'',default_browser_sender_id:els.browserSender.value||''};const saved=await api(`/api/templates/${encodeURIComponent(id)}`,jsonOptions('PUT',payload));const idx=state.templates.findIndex(t=>t.id===id);if(idx>=0)state.templates[idx]=saved;else state.templates.push(saved);renderTemplateSelect();els.templateSelect.value=id;toast('Template saved',saved.name,'success');}
async function deleteTemplate(){const id=els.templateSelect.value;if(!id||!confirm('Delete this template?'))return;await api(`/api/templates/${encodeURIComponent(id)}`,{method:'DELETE'});state.templates=state.templates.filter(t=>t.id!==id);renderTemplateSelect();toast('Template deleted');}
function templatePlaceholderInfo(){
  const fields=[els.subjectTemplate.value,els.bodyTemplate.value,els.bodyHtmlEditor.innerHTML,els.signatureHtmlEditor.innerHTML,els.ccTemplate.value,els.bccTemplate.value];const found=new Map();
  const add=(expression,conditional=false)=>{const parts=String(expression||'').split('|');const key=(parts.shift()||'').trim();if(!key)return;const fallback=parts.join('|').trim();const current=found.get(key)||{key,fallback:'',conditional:false};if(fallback&&!current.fallback)current.fallback=fallback;current.conditional=current.conditional||conditional;found.set(key,current);};
  fields.forEach(text=>{let match;const condition=/{{\s*#if\s+([^{}]+?)\s*}}/g;while((match=condition.exec(text||'')))add(match[1],true);const plain=/{{\s*(?!#if\b|\/if\b)([^{}]+?)\s*}}/g;while((match=plain.exec(text||'')))add(match[1],false);});return [...found.values()];
}
function normalizedColumnKey(value){return String(value||'').trim().toLocaleLowerCase().replace(/[\s_.-]+/g,'');}
function guessPlaceholderColumn(key){const lower=String(key||'').toLocaleLowerCase();if(lower==='name'&&state.headers.includes(els.nameColumn.value))return els.nameColumn.value;if(['email','recipient','to'].includes(lower)&&state.headers.includes(els.toColumn.value))return els.toColumn.value;const exact=state.headers.find(header=>header.toLocaleLowerCase()===lower);if(exact)return exact;const normalized=normalizedColumnKey(key);return state.headers.find(header=>normalizedColumnKey(header)===normalized)||'';}
function syncPlaceholderMappings({forceGuess=false}={}){const info=templatePlaceholderInfo();const next={};info.forEach(({key})=>{if(['_row','_today'].includes(key))return;const current=state.placeholderMappings[key];next[key]=!forceGuess&&current&&state.headers.includes(current)?current:guessPlaceholderColumn(key);});state.placeholderMappings=next;renderPlaceholderMappings(info);}
function currentSourceRow(){const renderedRow=state.rendered?.messages?.[state.messageIndex]?.row_number;const wanted=String(state.liveSheetRow||renderedRow||state.previewRows[0]?._row||'');return state.previewRows.find(row=>String(row._row)===wanted)||state.previewRows[0]||null;}
function sourceCell(row,column){if(!row||!column)return'';const override=state.rowOverrides[row._row]?.[column];return override!==undefined?override:(row[column]??'');}
function renderPlaceholderMappings(info=templatePlaceholderInfo()){els.placeholderMappingList.innerHTML='';if(!info.length){els.placeholderMappingList.innerHTML='<div class="empty-inline">Add a placeholder such as <code>{{Name}}</code> to the message to map it.</div>';return;}const sample=currentSourceRow();info.forEach(item=>{const row=document.createElement('div');row.className='placeholder-map-row';const token=document.createElement('div');token.className='placeholder-map-token';token.innerHTML=`<code>{{${esc(item.key)}}}</code>${item.conditional?'<span>condition</span>':''}`;row.append(token);if(['_row','_today'].includes(item.key)){const builtin=document.createElement('div');builtin.className='placeholder-map-built-in';builtin.textContent=item.key==='_row'?'Built in: sheet row':'Built in: today';row.append(builtin);const sampleEl=document.createElement('div');sampleEl.className='placeholder-map-sample';sampleEl.textContent=item.key==='_row'?(sample?`Sample: ${sample._row}`:'Built in'):new Date().toISOString().slice(0,10);row.append(sampleEl);els.placeholderMappingList.append(row);return;}const select=document.createElement('select');select.className='placeholder-map-select';const none=document.createElement('option');none.value='';none.textContent=item.fallback?`Use fallback “${item.fallback}”`:'Choose sheet column';select.append(none);state.headers.forEach(header=>{const option=document.createElement('option');option.value=header;option.textContent=header;select.append(option);});select.value=state.placeholderMappings[item.key]||'';select.addEventListener('change',()=>{state.placeholderMappings[item.key]=select.value;renderPlaceholderMappings();scheduleRender({syncMappings:false});});row.append(select);const sampleEl=document.createElement('div');sampleEl.className='placeholder-map-sample';const value=sourceCell(sample,select.value);sampleEl.textContent=select.value?(value?`Sample: ${value}`:'Sample: blank'):(item.fallback?`Fallback: ${item.fallback}`:'Not mapped');row.append(sampleEl);els.placeholderMappingList.append(row);});}
function autoMapPlaceholders(){syncPlaceholderMappings({forceGuess:true});scheduleRender({syncMappings:false});}
function renderPlaceholders(){els.placeholderList.innerHTML='';const keys=[...state.headers,'_row','_today'];if(!keys.length){els.placeholderList.innerHTML='<span class="empty-inline">Load a source to see columns.</span>';return;}keys.forEach(key=>{const b=document.createElement('button');b.type='button';b.className='placeholder-pill';b.textContent=`{{${key}}}`;b.addEventListener('click',()=>insertIntoActive(`{{${key}}}`));els.placeholderList.append(b);});}
function insertIntoActive(text){const el=state.activeEditor||els.bodyTemplate;if(el.isContentEditable){el.focus();document.execCommand('insertText',false,text);scheduleRender();return;}const start=el.selectionStart??el.value.length,end=el.selectionEnd??el.value.length;el.value=el.value.slice(0,start)+text+el.value.slice(end);el.focus();el.setSelectionRange(start+text.length,start+text.length);scheduleRender();}
function renderSnippets(){els.snippetList.innerHTML='';state.snippets.forEach(s=>{const b=document.createElement('button');b.type='button';b.className='snippet-pill';b.textContent=s.name;b.title=s.content;b.addEventListener('click',()=>insertIntoActive(s.content));els.snippetList.append(b);});if(!state.snippets.length)els.snippetList.innerHTML='<span class="empty-inline">No snippets yet.</span>';}
async function saveSnippetFromDialog(){const name=els.snippetName.value.trim(),content=els.snippetContent.value;if(!name||!content)return;const id=`snippet-${Date.now()}`;try{const saved=await api(`/api/snippets/${id}`,jsonOptions('PUT',{id,name,content}));state.snippets.push(saved);renderSnippets();els.snippetName.value='';els.snippetContent.value='';toast('Snippet saved',saved.name,'success');}catch(error){toast('Could not save snippet',error.message,'error');}}
async function uploadAttachments(files){for(const file of [...files]){const form=new FormData();form.append('file',file);try{const item=await api('/api/attachments',{method:'POST',body:form});state.attachments.unshift(item);state.selectedAttachmentIds.add(item.id);}catch(error){toast(`Could not add ${file.name}`,error.message,'error');}}renderAttachments();scheduleRender();els.attachmentFile.value='';}
function renderAttachments(){els.attachmentList.innerHTML='';state.attachments.forEach(a=>{const unit=document.createElement('span');unit.className='attachment-unit';const b=document.createElement('button');b.type='button';b.className=`attachment-pill ${state.selectedAttachmentIds.has(a.id)?'is-selected':''}`;b.textContent=`${a.name} · ${formatBytes(a.size)}`;b.addEventListener('click',()=>{state.selectedAttachmentIds.has(a.id)?state.selectedAttachmentIds.delete(a.id):state.selectedAttachmentIds.add(a.id);renderAttachments();scheduleRender();});unit.append(b);if((a.mime_type||'').startsWith('image/')){const inline=document.createElement('button');inline.type='button';inline.className='inline-image-button';inline.textContent='Inline';inline.title='Insert this image into the HTML message using a Content-ID reference';inline.addEventListener('click',()=>{state.selectedAttachmentIds.add(a.id);els.bodyHtmlEditor.focus();document.execCommand('insertHTML',false,`<img src="cid:${a.id}" alt="${esc(a.name)}" style="max-width:100%;height:auto">`);renderAttachments();setEditorTab('html');scheduleRender();});unit.append(inline);}els.attachmentList.append(unit);});if(!state.attachments.length)els.attachmentList.innerHTML='<span class="empty-inline">No uploaded attachments.</span>';}
function formatBytes(n){if(n<1024)return `${n} B`;if(n<1024*1024)return `${(n/1024).toFixed(1)} KB`;return `${(n/1024/1024).toFixed(1)} MB`;}

function renderPayload(){return {import_id:state.importId,sheet:els.sheetSelect.value,header_row:els.headerRow.value?Number(els.headerRow.value):null,to_column:els.toColumn.value,name_column:els.nameColumn.value,cc_column:els.ccColumn.value,bcc_column:els.bccColumn.value,attachment_column:els.attachmentColumn.value,subject:els.subjectTemplate.value,body:els.bodyTemplate.value,body_html:els.bodyHtmlEditor.innerHTML,signature_html:els.signatureHtmlEditor.innerHTML,cc_template:els.ccTemplate.value,bcc_template:els.bccTemplate.value,attachment_ids:[...state.selectedAttachmentIds],filter_column:els.filterColumn.value,filter_operator:els.filterOperator.value,filter_value:els.filterValue.value,sort_column:els.sortColumn.value,sort_direction:els.sortDirection.value,selected_rows:state.selectedRows.size===state.allRowNumbers.length?null:[...state.selectedRows],row_overrides:state.rowOverrides,limit:Number(els.rowLimit.value||0),trim_values:els.trimValues.checked,placeholder_mappings:Object.fromEntries(Object.entries(state.placeholderMappings).filter(([,column])=>column))};}
function scheduleRender({syncMappings=true}={}){
  if(syncMappings)syncPlaceholderMappings();renderLiveSheet();
  clearTimeout(state.renderTimer);invalidateReview();
  const selectedCount=state.selectedRows.size;
  if(!state.importId||!els.toColumn.value||selectedCount>AUTO_RENDER_ROW_LIMIT)return;
  state.renderTimer=setTimeout(()=>renderCampaign(false),650);
}
async function renderCampaign(showToast=true){
  clearTimeout(state.renderTimer);
  if(!state.importId||!els.toColumn.value){if(showToast)toast('Source mapping needed','Load a source and select the recipient column first.','error');return;}
  const requestId=++state.renderRequestId, revision=state.renderRevision, payload=renderPayload();
  try{
    const result=await api('/api/render',jsonOptions('POST',payload));
    if(requestId!==state.renderRequestId||revision!==state.renderRevision)return;
    state.rendered=result;state.renderDirty=false;state.messageIndex=Math.min(state.messageIndex,Math.max(0,result.messages.length-1));clearConfirmation();renderValidation();renderReview();updateFinalSummary();
    if(showToast)toast('Messages rendered',`${result.valid} valid · ${result.invalid} with errors · ${result.with_warnings} with warnings`,result.invalid?'error':'success');
  }catch(error){if(requestId===state.renderRequestId){state.renderDirty=true;updateFinalSummary();if(showToast)toast('Could not render messages',error.message,'error');}}
}
function renderValidation(){const r=state.rendered;if(!r){els.validationSummary.innerHTML='<div><b>0</b><span>rendered</span></div><div class="good"><b>0</b><span>valid</span></div><div class="bad"><b>0</b><span>errors</span></div><div class="warn"><b>0</b><span>warnings</span></div>';els.validationList.innerHTML='<div class="empty-card">Render messages to see row-level validation.</div>';return;}els.validationSummary.innerHTML=`<div><b>${r.total}</b><span>rendered</span></div><div class="good"><b>${r.valid}</b><span>valid</span></div><div class="bad"><b>${r.invalid}</b><span>errors</span></div><div class="warn"><b>${r.with_warnings}</b><span>warnings</span></div>`;els.validationList.innerHTML='';r.messages.slice(0,120).forEach((m,i)=>{const d=document.createElement('button');d.type='button';d.className=`validation-item ${m.errors.length?'has-error':m.warnings.length?'has-warning':''}`;const issue=[...m.errors,...m.warnings].join(' · ')||'Ready';d.innerHTML=`<span class="row-label">Row ${esc(m.row_number)}</span><span class="issues">${esc(m.display_name||m.to)} · ${esc(issue)}</span><span class="status-tag ${m.errors.length?'bad':m.warnings.length?'warn':'good'}">${m.errors.length?'Error':m.warnings.length?'Warning':'Valid'}</span>`;d.addEventListener('click',()=>{state.messageIndex=i;renderReview();});els.validationList.append(d);});if(!r.messages.length)els.validationList.innerHTML='<div class="empty-card">No rows match the current selection/filter.</div>';}
function renderReview(){
  const messages=state.rendered?.messages||[];if(!messages.length){els.reviewEmpty.classList.remove('is-hidden');els.reviewContent.classList.add('is-hidden');els.reviewPosition.textContent='No rendered messages';els.htmlPreview.removeAttribute('srcdoc');return;}
  const m=messages[state.messageIndex];els.reviewEmpty.classList.add('is-hidden');els.reviewContent.classList.remove('is-hidden');els.reviewPosition.textContent=`${state.messageIndex+1} of ${messages.length} · row ${m.row_number}`;els.reviewStatus.innerHTML='';if(m.errors.length)addStatus('Error', 'bad');else addStatus('Valid','good');m.warnings.forEach(w=>addStatus(w,'warn'));els.reviewTo.value=m.to;els.reviewCc.value=m.cc;els.reviewBcc.value=m.bcc;els.reviewSubject.value=m.subject;els.reviewBody.value=m.body;[els.reviewTo,els.reviewCc,els.reviewBcc,els.reviewSubject,els.reviewBody].forEach(x=>x.setAttribute('dir','auto'));
  if(m.body_html){els.htmlPreviewWrap.classList.remove('is-hidden');const previewHtml=m.body_html.replace(/cid:([a-zA-Z0-9._-]+)/g,'/api/attachments/$1/content');const origin=location.origin.replace(/["'<>\s]/g,'');els.htmlPreview.srcdoc=`<!doctype html><meta charset="utf-8"><meta name="referrer" content="no-referrer"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src ${origin} data: blob:; style-src 'unsafe-inline'; connect-src 'none'; font-src 'none'; media-src 'none'; frame-src 'none'; form-action 'none'; base-uri 'none'"><body style="font:14px system-ui;line-height:1.55;padding:16px" dir="auto">${previewHtml}</body>`;}else{els.htmlPreviewWrap.classList.add('is-hidden');els.htmlPreview.removeAttribute('srcdoc');}
  const names=(m.attachments||[]).map(id=>state.attachments.find(a=>a.id===id)?.name||id);els.reviewMeta.innerHTML=`<span>${esc(m.display_name||'')}</span><span>${names.length?`${names.length} attachment${names.length===1?'':'s'}: ${esc(names.join(', '))}`:'No attachments'}</span>`;state.liveSheetRow=String(m.row_number);renderLiveSheet();renderPlaceholderMappings();
}
function addStatus(text,kind){const s=document.createElement('span');s.className=`status-tag ${kind}`;s.textContent=text;els.reviewStatus.append(s);}
async function commitReviewEdit(){
  const m=state.rendered?.messages?.[state.messageIndex];if(!m)return;clearConfirmation();
  m.to=els.reviewTo.value.trim();m.cc=els.reviewCc.value.trim();m.bcc=els.reviewBcc.value.trim();m.subject=els.reviewSubject.value;m.body=els.reviewBody.value;
  const preserved=(m.errors||[]).filter(e=>!/^Recipient is blank\.$/.test(e)&&!/^Invalid (recipient|Cc|Bcc|address):/.test(e)&&e!==SUBJECT_LINE_ERROR);m.errors=[...preserved];
  const invalid=[...splitAddressClient(m.to),...splitAddressClient(m.cc),...splitAddressClient(m.bcc)].filter(a=>!validEmailClient(a));if(!splitAddressClient(m.to).length)m.errors.push('Recipient is blank.');if(invalid.length)m.errors.push(`Invalid address: ${invalid.join(', ')}`);if(/\r|\n/.test(m.subject))m.errors.push(SUBJECT_LINE_ERROR);
  state.rendered.invalid=state.rendered.messages.filter(x=>x.errors.length).length;state.rendered.valid=state.rendered.messages.length-state.rendered.invalid;state.renderDirty=true;
  const requestId=++state.batchRequestId;
  try{const result=await api('/api/batch-id',jsonOptions('POST',{messages:stripSources(state.rendered.messages)}));if(requestId!==state.batchRequestId)return;state.rendered.batch_id=result.batch_id;state.renderDirty=false;}
  catch(error){if(requestId===state.batchRequestId){state.renderDirty=true;toast('Could not update messages',error.message,'error');}}
  renderValidation();renderReview();updateFinalSummary();
}
function handleReviewBodyInput(){
  const m=state.rendered?.messages?.[state.messageIndex];if(!m?.body_html)return;
  m.body_html='';m.warnings||=[];if(!m.warnings.includes(HTML_EDIT_WARNING))m.warnings.push(HTML_EDIT_WARNING);state.renderDirty=true;clearConfirmation();els.htmlPreviewWrap.classList.add('is-hidden');els.htmlPreview.removeAttribute('srcdoc');renderValidation();updateFinalSummary();
}
function splitAddressClient(v){return String(v||'').split(/[;,\n]+/).map(x=>x.trim()).filter(Boolean);}
function validEmailClient(value){
  const address=String(value||'').trim();
  const at=address.indexOf('@');
  if(!address||address.length>254||at<=0||at!==address.lastIndexOf('@'))return false;
  const local=address.slice(0,at),domain=address.slice(at+1);
  if(!/^[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+(?:\.[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+)*$/.test(local)||new TextEncoder().encode(local).length>64)return false;
  if(domain.length>253||!domain.includes('.'))return false;
  const label=/^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$/;
  return domain.split('.').every(part=>label.test(part));
}
function stripSources(messages){return messages.map(({source,...m})=>m);}

function updateModeUI(){const mode=currentMode();qsa('.mode-card').forEach(c=>c.classList.toggle('is-selected',q('input',c).checked));els.browserDelivery.classList.toggle('is-hidden',mode!=='browser');els.gmailDelivery.classList.toggle('is-hidden',!['draft','send'].includes(mode));els.sendConfirmation.classList.toggle('is-hidden',mode!=='send');clearConfirmation();updateBrowserSenderSummary();updateFinalSummary();}
function expectedConfirmation(){const r=state.rendered;return r&&currentMode()==='send'?`SEND ${r.messages.length}`:'';}
function updateFinalSummary(){
  const r=state.rendered,mode=currentMode();
  const sender=mode==='browser'?(state.browserSenders.find(s=>s.id===els.browserSender.value)?.expected_email||'Not selected'):['draft','send'].includes(mode)?(els.gmailAccount.value||'Not selected'):'Not used';
  const schedule=els.scheduleAt.value?new Date(els.scheduleAt.value).toLocaleString():'When queued';
  els.finalSummary.innerHTML=`<div class="summary-card"><span>Messages</span><strong>${r?r.total:0} · ${r?r.invalid:0} errors${state.renderDirty?' · needs re-check':''}</strong></div><div class="summary-card"><span>Mode</span><strong>${mode.replace('_',' ')}</strong></div><div class="summary-card"><span>Sender</span><strong>${esc(sender)}</strong></div><div class="summary-card"><span>Timing</span><strong>${esc(schedule)}</strong></div>`;
  const expected=expectedConfirmation();els.expectedConfirm.textContent=expected;els.confirmText.placeholder=expected;
  const okay=!!r&&!state.renderDirty&&r.total>0&&r.invalid===0&&(!['draft','send'].includes(mode)||!!els.gmailAccount.value)&&(mode!=='browser'||!!els.browserSender.value)&&(mode!=='send'||els.confirmText.value.trim()===expected);
  const count=r?.total||0;
  const plural=count===1?'message':'messages';
  let action=els.scheduleAt.value?`Schedule ${count} ${plural}`:mode==='dry_run'?`Run dry test · ${count}`:mode==='browser'?`Open ${count} browser draft${count===1?'':'s'}`:mode==='draft'?`Create ${count} Gmail draft${count===1?'':'s'}`:`Send ${count} ${plural}`;
  if(!r)action='Check messages before queueing';
  els.queueCampaignButton.disabled=!okay;
  els.queueCampaignButton.textContent=action;
  els.queueCampaignButton.classList.toggle('danger',mode==='send');
}
async function queueCampaign(){
  const r=state.rendered;if(!r||state.renderDirty){toast('Render changed messages first','Messages changed or are still updating. Check them again.','error');return;}const mode=currentMode();
  let scheduled='';if(els.scheduleAt.value){const date=new Date(els.scheduleAt.value);if(Number.isNaN(date.getTime())){toast('Invalid schedule','Choose a valid date and time.','error');return;}scheduled=date.toISOString();}
  const payload={name:els.campaignName.value.trim(),source_name:state.source?.filename||'',mode,account:els.gmailAccount.value||'',browser_sender_id:els.browserSender.value||'',batch_id:r.batch_id,messages:stripSources(r.messages),skip_duplicates:els.skipDuplicates.checked,throttle_ms:Number(els.throttleMs.value||0),scheduled_at:scheduled,confirm_text:els.confirmText.value};busy(true,scheduled?'Scheduling campaign…':'Queueing campaign…',`${r.total} messages`);try{const campaign=await api('/api/campaigns',jsonOptions('POST',payload));toast(scheduled?'Campaign scheduled':'Campaign queued',`${campaign.name} · ${campaign.status}`,'success',6500);clearConfirmation();setView('queue');await refreshQueue();}catch(error){toast('Campaign was not queued',error.message,'error',9000);}finally{busy(false);updateFinalSummary();}
}
function csvCell(value){let text=String(value??'');if(/^[\s]*[=+\-@]/.test(text))text=`'${text}`;return `"${text.replace(/"/g,'""')}"`;}
function exportReviewCsv(){const r=state.rendered;if(!r)return;const rows=[['Row','Name','To','Cc','Bcc','Subject','Body','Errors','Warnings'],...r.messages.map(m=>[m.row_number,m.display_name,m.to,m.cc,m.bcc,m.subject,m.body,m.errors.join('; '),m.warnings.join('; ')])];const csv=rows.map(row=>row.map(csvCell).join(',')).join('\r\n');const blob=new Blob(['\ufeff'+csv],{type:'text/csv;charset=utf-8'});const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download=`maildesk-review-${r.batch_id.slice(0,8)}.csv`;a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000);}

async function refreshAccountsAndBrowsers(forceBrowserRefresh=false){
  try{const profileUrl=forceBrowserRefresh?'/api/browser-profiles?refresh=true':'/api/browser-profiles';const [accounts,profiles,senders,settings]=await Promise.all([api('/api/accounts'),api(profileUrl),api('/api/browser-senders'),api('/api/settings')]);state.gmailAccounts=accounts;state.browserProfiles=profiles;state.browserSenders=senders;state.settings=settings;renderAccounts();renderBrowserProfiles();renderBrowserSenders();renderSenderSelects();els.maxBatchSize.value=settings.max_batch_size;els.defaultThrottle.value=settings.default_throttle_ms;if(!els.throttleMs.dataset.touched)els.throttleMs.value=settings.default_throttle_ms;}
  catch(error){toast('Could not refresh accounts',error.message,'error');}
}
function renderAccounts(){els.accountList.innerHTML='';state.gmailAccounts.forEach(a=>{const d=document.createElement('div');d.className='account-card';const problem=a.credential_error?`<div class="callout warning">${esc(a.credential_error)}</div>`:'';d.innerHTML=`<div class="account-avatar">${esc(a.email[0]?.toUpperCase()||'G')}</div><div class="account-main"><strong>${esc(a.email)}</strong><span>Updated ${new Date(a.updated_at).toLocaleString()}</span><div class="account-meta"><span class="pill ${a.gmail===true?'good':''}">Gmail</span><span class="pill ${a.sheets===true?'good':''}">Sheets</span></div>${problem}</div><button class="button ghost-danger small">Disconnect</button>`;q('button',d).addEventListener('click',()=>disconnectAccount(a.email));els.accountList.append(d);});if(!state.gmailAccounts.length)els.accountList.innerHTML='<div class="empty-card">No Gmail accounts connected.</div>';}
function renderBrowserProfiles(){const prev=els.browserProfile.value;els.browserProfile.innerHTML='';state.browserProfiles.forEach(p=>{const o=document.createElement('option');o.value=p.profile_id;o.textContent=`${p.browser_name} · ${p.profile_name}${p.primary_email?` · ${p.primary_email}`:''}`;els.browserProfile.append(o);});if(state.browserProfiles.some(p=>p.profile_id===prev))els.browserProfile.value=prev;updateProfileEmailHints();}
function updateProfileEmailHints(){const p=state.browserProfiles.find(x=>x.profile_id===els.browserProfile.value);els.profileEmails.innerHTML='';(p?.emails||[]).forEach(email=>{const o=document.createElement('option');o.value=email;els.profileEmails.append(o);});renderDetectedBrowserAccounts();}
function renderDetectedBrowserAccounts(){const p=state.browserProfiles.find(x=>x.profile_id===els.browserProfile.value);els.detectedBrowserAccounts.innerHTML='';const accounts=p?.gmail_accounts||[];if(!p){els.browserDetectionHint.textContent='No browser profile is available.';return;}if(!accounts.length){els.detectedBrowserAccounts.innerHTML='<div class="empty-inline">No ordered Gmail session accounts found in this profile.</div>';els.browserDetectionHint.textContent=(p.emails||[]).length?'MailDesk found profile email hints, but not enough browser-session data to determine Gmail account indexes. Use the manual fallback below.':'Sign in to Gmail in this browser profile, then click Rescan browsers. You can also use the manual fallback.';return;}els.browserDetectionHint.textContent='Detected from the browser’s cached Google session. Select an account, then verify it once in Gmail before use.';accounts.forEach(account=>{const button=document.createElement('button');button.type='button';button.className='detected-browser-account';button.classList.toggle('is-selected',Number(els.gmailSlot.value)===Number(account.slot)&&els.browserExpectedEmail.value.toLocaleLowerCase()===String(account.email).toLocaleLowerCase());button.innerHTML=`<span class="detected-account-index">${account.slot}</span><span><strong>${esc(account.email)}</strong><small>${account.valid===false?'Session may need sign-in':'Signed-in Gmail account'} · ${esc(p.browser_name)} ${esc(p.profile_name)}</small></span>`;button.addEventListener('click',()=>{els.gmailSlot.value=account.slot;els.browserExpectedEmail.value=account.email;if(!els.browserSenderLabel.value.trim())els.browserSenderLabel.value=account.email;renderDetectedBrowserAccounts();});els.detectedBrowserAccounts.append(button);});}
function selectFirstDetectedBrowserAccount(){const p=state.browserProfiles.find(x=>x.profile_id===els.browserProfile.value);const first=p?.gmail_accounts?.[0];if(first){els.gmailSlot.value=first.slot;els.browserExpectedEmail.value=first.email;}else{els.gmailSlot.value=0;els.browserExpectedEmail.value='';}renderDetectedBrowserAccounts();}
async function rescanBrowserProfiles(){const label=els.rescanBrowserProfilesButton.textContent;els.rescanBrowserProfilesButton.disabled=true;els.rescanBrowserProfilesButton.textContent='Scanning…';try{await refreshAccountsAndBrowsers(true);toast('Browsers rescanned','Detected Gmail accounts were refreshed.','success');}catch(error){toast('Browser scan failed',error.message,'error');}finally{els.rescanBrowserProfilesButton.disabled=false;els.rescanBrowserProfilesButton.textContent=label;}}
function renderBrowserSenders(){els.browserSenderList.innerHTML='';state.browserSenders.forEach(s=>{const p=state.browserProfiles.find(x=>x.browser_id===s.browser_id&&x.profile_dir===s.profile_dir);const fresh=isSenderFresh(s);const d=document.createElement('div');d.className='browser-card';d.innerHTML=`<div class="browser-avatar">${esc((p?.browser_name||s.browser_id)[0].toUpperCase())}</div><div class="browser-main"><strong>${esc(s.label)} · ${esc(s.expected_email)}</strong><span>${esc(p?.browser_name||s.browser_id)} · ${esc(p?.profile_name||s.profile_dir)} · account ${s.gmail_slot}</span><div class="browser-meta"><span class="pill ${fresh?'good':''}">${fresh?'Verified':'Verify before use'}</span></div></div><div class="button-row"><button class="button secondary small verify">Verify</button><button class="button ghost small edit">Edit</button><button class="button ghost-danger small delete">Delete</button></div>`;q('.verify',d).addEventListener('click',()=>startVerifyBrowserSender(s.id));q('.edit',d).addEventListener('click',()=>editBrowserSender(s));q('.delete',d).addEventListener('click',()=>deleteBrowserSender(s.id));els.browserSenderList.append(d);});if(!state.browserSenders.length)els.browserSenderList.innerHTML='<div class="empty-card">No browser senders yet.</div>';}
function fillAccountSelect(select,accounts,previous){select.innerHTML='';accounts.forEach(a=>{const o=document.createElement('option');o.value=a.email;o.textContent=a.email;select.append(o);});if(accounts.some(a=>a.email===previous))select.value=previous;}
function renderSenderSelects(){const g=els.gmailAccount.value,b=els.browserSender.value,gs=els.googleSheetAccount.value;fillAccountSelect(els.gmailAccount,state.gmailAccounts.filter(a=>a.gmail===true),g);fillAccountSelect(els.googleSheetAccount,state.gmailAccounts.filter(a=>a.sheets===true),gs);els.browserSender.innerHTML='';state.browserSenders.forEach(s=>{const o=document.createElement('option');o.value=s.id;o.textContent=`${s.label} · ${s.expected_email} · account ${s.gmail_slot}`;els.browserSender.append(o);});if(state.browserSenders.some(s=>s.id===b))els.browserSender.value=b;updateBrowserSenderSummary();updateFinalSummary();}
function updateBrowserSenderSummary(){const s=state.browserSenders.find(x=>x.id===els.browserSender.value);if(!s){els.browserSenderSummary.innerHTML='<div class="sender-avatar">B</div><div><strong>No sender selected</strong><span>Add a browser sender under Senders.</span></div><button class="button secondary small" id="verifySelectedBrowserButton2">Configure</button>';q('#verifySelectedBrowserButton2',els.browserSenderSummary)?.addEventListener('click',()=>setView('accounts'));return;}const p=state.browserProfiles.find(x=>x.browser_id===s.browser_id&&x.profile_dir===s.profile_dir);els.browserSenderSummary.innerHTML=`<div class="sender-avatar">${esc(s.expected_email[0].toUpperCase())}</div><div><strong>${esc(s.expected_email)}</strong><span>${esc(p?.browser_name||s.browser_id)} · ${esc(p?.profile_name||s.profile_dir)} · account ${s.gmail_slot} · ${isSenderFresh(s)?'verified':'verify before use'}</span></div><button class="button secondary small" id="verifySelectedBrowserButton2">Verify</button>`;q('#verifySelectedBrowserButton2',els.browserSenderSummary).addEventListener('click',()=>startVerifyBrowserSender(s.id));}
function isSenderFresh(s){if(!s?.verified_at)return false;const verified=new Date(s.verified_at).getTime();return Number.isFinite(verified)&&Date.now()-verified<30*60*1000;}
function editBrowserSender(s){els.browserSenderId.value=s.id;els.browserSenderLabel.value=s.label;els.gmailSlot.value=s.gmail_slot;els.browserExpectedEmail.value=s.expected_email;const p=state.browserProfiles.find(x=>x.browser_id===s.browser_id&&x.profile_dir===s.profile_dir);if(p)els.browserProfile.value=p.profile_id;updateProfileEmailHints();renderDetectedBrowserAccounts();window.scrollTo({top:0,behavior:'smooth'});}
function resetBrowserSenderForm(){els.browserSenderId.value='';els.browserSenderLabel.value='';els.gmailSlot.value=0;els.browserExpectedEmail.value='';if(state.browserProfiles[0])els.browserProfile.value=state.browserProfiles[0].profile_id;updateProfileEmailHints();selectFirstDetectedBrowserAccount();}
async function saveBrowserSender(){const profile=state.browserProfiles.find(p=>p.profile_id===els.browserProfile.value);if(!profile){toast('No browser profile','Rescan installed browsers first.','error');return;}const id=els.browserSenderId.value||`route-${Date.now()}`;const payload={id,label:els.browserSenderLabel.value.trim()||`${els.browserExpectedEmail.value.trim()} browser`,browser_id:profile.browser_id,profile_dir:profile.profile_dir,gmail_slot:Number(els.gmailSlot.value||0),expected_email:els.browserExpectedEmail.value.trim()};try{await api(`/api/browser-senders/${encodeURIComponent(id)}`,jsonOptions('PUT',payload));resetBrowserSenderForm();await refreshAccountsAndBrowsers();toast('Browser sender saved',payload.expected_email,'success');}catch(error){toast('Could not save sender',error.message,'error');}}
async function deleteBrowserSender(id){if(!confirm('Delete this browser sender?'))return;try{await api(`/api/browser-senders/${encodeURIComponent(id)}`,{method:'DELETE'});await refreshAccountsAndBrowsers();}catch(error){toast('Could not delete sender',error.message,'error');}}
async function startVerifyBrowserSender(id){state.verifyingSenderId=id;try{const result=await api(`/api/browser-senders/${encodeURIComponent(id)}/verify/open`,{method:'POST'});els.verifyBrowserText.innerHTML=`Check the browser window that opened and confirm it shows <strong>${esc(result.expected_email)}</strong> as account ${result.gmail_slot}.`;els.verifyBrowserDialog.showModal();}catch(error){state.verifyingSenderId='';toast('Could not open Gmail',error.message,'error');}}
async function confirmBrowserVerified(){if(!state.verifyingSenderId)return;try{await api(`/api/browser-senders/${encodeURIComponent(state.verifyingSenderId)}/verify/confirm`,{method:'POST'});await refreshAccountsAndBrowsers();toast('Browser sender verified','','success');}catch(error){toast('Could not record verification',error.message,'error');}finally{state.verifyingSenderId='';}}
async function connectGoogle(file){if(!file)return;const form=new FormData();form.append('client_secret',file);form.append('include_sheets',els.includeSheetsScope.checked?'true':'false');busy(true,'Preparing Google sign-in…','A Google authorization tab will open.');try{const result=await api('/api/accounts/google/start',{method:'POST',body:form});const popup=window.open(result.auth_url,'_blank');if(!popup)toast('Pop-up blocked','Allow pop-ups, then connect again.','error');else{toast('Google sign-in opened','Complete authorization in the new tab. Accounts will refresh automatically.');let attempts=0,pollBusy=false;const poll=setInterval(async()=>{if(pollBusy)return;pollBusy=true;attempts++;try{await refreshAccountsAndBrowsers();if(attempts>=40||popup.closed)clearInterval(poll);}catch{if(attempts>=40)clearInterval(poll);}finally{pollBusy=false;}},1500);}}catch(error){toast('Could not start Google sign-in',error.message,'error');}finally{busy(false);els.oauthFile.value='';}}
async function disconnectAccount(email){if(!confirm(`Disconnect ${email}?`))return;try{await api(`/api/accounts/${encodeURIComponent(email)}`,{method:'DELETE'});await refreshAccountsAndBrowsers();toast('Account disconnected',email);}catch(error){toast('Could not disconnect account',error.message,'error');}}

async function refreshQueue(){try{state.campaigns=await api('/api/campaigns?limit=100');els.queueBadge.textContent=state.campaigns.filter(c=>['Queued','Running','Paused','Scheduled'].includes(c.status)).length;els.queueList.innerHTML='';if(!state.campaigns.length){els.queueList.innerHTML='<div class="empty-card">No campaigns yet.</div>';return;}state.campaigns.forEach(c=>{const done=c.success+c.failed+c.skipped,pct=c.total?Math.round(done/c.total*100):0,terminal=['Completed','CompletedWithErrors','Cancelled'].includes(c.status);const card=document.createElement('div');card.className='queue-card';card.innerHTML=`<div class="queue-card-head"><div class="sender-avatar">${c.mode==='send'?'➤':c.mode==='draft'?'□':c.mode==='browser'?'◫':'◇'}</div><div><h3>${esc(c.name)}</h3><p>${esc(c.mode.replace('_',' '))} · ${esc(c.account||c.browser_sender_id||'local')} · ${new Date(c.created_at).toLocaleString()}</p></div><span class="status-tag ${c.failed||c.status==='CompletedWithErrors'?'bad':c.status==='Completed'?'good':c.status==='Paused'?'warn':''}">${esc(c.status)}</span></div><div class="queue-progress"><span style="width:${pct}%"></span></div><div class="queue-stats"><span>${c.success} success</span><span>${c.skipped} skipped</span><span>${c.failed} failed</span><span>${Math.max(0,c.total-done)} remaining</span>${c.scheduled_at?`<span>scheduled ${new Date(c.scheduled_at).toLocaleString()}</span>`:''}</div><div class="queue-actions"><button class="button secondary small details">Details</button><button class="button secondary small duplicate">Duplicate</button>${c.status==='Running'||c.status==='Queued'||c.status==='Scheduled'?'<button class="button secondary small pause">Pause</button>':''}${c.status==='Paused'?'<button class="button primary small resume">Resume</button>':''}${c.failed?'<button class="button secondary small retry">Retry failed</button>':''}${!terminal?'<button class="button ghost-danger small cancel">Cancel</button>':''}</div>${c.last_error?`<div class="callout warning">${esc(c.last_error)}</div>`:''}`;q('.details',card).addEventListener('click',()=>toggleCampaignDetails(card,c.id));q('.duplicate',card).addEventListener('click',()=>duplicateCampaign(c.id));q('.pause',card)?.addEventListener('click',()=>queueAction(c.id,'pause'));q('.resume',card)?.addEventListener('click',()=>queueAction(c.id,'resume'));q('.retry',card)?.addEventListener('click',()=>queueAction(c.id,'retry-failed'));q('.cancel',card)?.addEventListener('click',()=>queueAction(c.id,'cancel'));els.queueList.append(card);});}catch(error){toast('Could not load queue',error.message,'error');}}

async function duplicateCampaign(id){
  try{
    const c=await api(`/api/campaigns/${id}`);
    const messages=c.items.map(i=>({row_number:i.row_number,display_name:'',to:i.recipient,cc:i.cc,bcc:i.bcc,subject:i.subject,body:i.body,body_html:i.body_html,attachments:i.attachments||[],errors:[],warnings:[]}));
    const hash=await api('/api/batch-id',jsonOptions('POST',{messages}));
    state.rendered={total:messages.length,valid:messages.length,invalid:0,with_warnings:0,batch_id:hash.batch_id,messages,source:{source_type:'duplicated',filename:c.source_name||'Previous campaign'}};
    state.renderRevision+=1;state.renderDirty=false;state.source=state.rendered.source;state.messageIndex=0;els.campaignName.value=`Copy of ${c.name}`;
    const modeRadio=q(`input[name="mode"][value="${c.mode}"]`);if(modeRadio)modeRadio.checked=true;
    if(c.account&&state.gmailAccounts.some(a=>a.email===c.account))els.gmailAccount.value=c.account;
    if(c.browser_sender_id&&state.browserSenders.some(b=>b.id===c.browser_sender_id))els.browserSender.value=c.browser_sender_id;
    clearConfirmation();renderValidation();renderReview();updateModeUI();setView('campaign');setStep(5);
    toast('Campaign duplicated','Review the copied messages before queueing.','success',7000);
  }catch(error){toast('Could not duplicate campaign',error.message,'error');}
}

async function toggleCampaignDetails(card,id){
  const existing=q('.queue-items',card);if(existing){existing.remove();return;}
  try{
    const c=await api(`/api/campaigns/${encodeURIComponent(id)}/detail?limit=${QUEUE_DETAIL_ROW_LIMIT}&needs_review_limit=${QUEUE_DETAIL_ROW_LIMIT}`);
    const items=Array.isArray(c.items)?c.items:[],wrap=document.createElement('div');wrap.className='table-scroll queue-items';
    if(Number(c.total||0)>items.length){const note=document.createElement('div');note.className='callout';note.textContent=`Showing ${items.length.toLocaleString()} of ${Number(c.total||0).toLocaleString()} items.`;wrap.append(note);}
    const table=document.createElement('table');table.className='data-table';table.innerHTML='<thead><tr><th>#</th><th>Row</th><th>Recipient</th><th>Subject</th><th>Status</th><th>Attempts</th><th>Error</th><th>Action</th></tr></thead>';const body=document.createElement('tbody');
    items.forEach(item=>{const tr=document.createElement('tr');[item.ordinal,item.row_number,item.recipient,item.subject,item.status,item.attempts,item.error||''].forEach(value=>{const td=document.createElement('td');td.textContent=value;td.title=value;tr.append(td);});const actions=document.createElement('td');
      if(item.status==='NeedsReview'){const yes=document.createElement('button'),no=document.createElement('button');yes.type=no.type='button';yes.className='button primary small';no.className='button secondary small';yes.textContent=c.mode==='draft'?'Draft exists':'Sent';no.textContent=c.mode==='draft'?'No draft':'Not sent';const resolve=async outcome=>{const completed=outcome==='resolve-sent',wording=c.mode==='draft'?(completed?'a draft exists':'no draft was created'):(completed?'the message was sent':'the message was not sent');if(!confirm(`Confirm ${wording}?`))return;yes.disabled=no.disabled=true;try{await api(`/api/campaigns/${encodeURIComponent(id)}/items/${item.id}/${outcome}`,{method:'POST'});await refreshQueue();}catch(error){toast('Could not resolve outcome',error.message,'error');yes.disabled=no.disabled=false;}};yes.addEventListener('click',()=>resolve('resolve-sent'));no.addEventListener('click',()=>resolve('resolve-not-sent'));const row=document.createElement('div');row.className='button-row';row.append(yes,no);actions.append(row);}else actions.textContent='—';tr.append(actions);body.append(tr);});
    table.append(body);wrap.append(table);card.append(wrap);
  }catch(error){toast('Could not load campaign details',error.message,'error');}
}
async function queueAction(id,action){try{await api(`/api/campaigns/${id}/${action}`,{method:'POST'});await refreshQueue();toast('Queue updated',action.replace('-',' '),'success');}catch(error){toast('Queue action failed',error.message,'error');}}
async function refreshHistory(){try{const rows=await api('/api/history?limit=500');els.historyTable.innerHTML='';const headers=['Time','Campaign','Mode','Account','Row','Recipient','Subject','Result','Remote ID','Error'];const thead=document.createElement('thead'),tr=document.createElement('tr');headers.forEach(h=>{const th=document.createElement('th');th.textContent=h;tr.append(th);});thead.append(tr);els.historyTable.append(thead);const body=document.createElement('tbody');rows.forEach(r=>{const tr=document.createElement('tr');const values=[new Date(r.timestamp_utc).toLocaleString(),r.campaign_id,r.mode,r.account,r.row_number,r.recipient,r.subject,r.result,r.remote_id,r.error];values.forEach((v,i)=>{const td=document.createElement('td');td.textContent=v||'';td.title=v||'';if(i===7)td.className=r.result==='Success'?'result-success':r.result==='Failed'||r.result==='Uncertain'?'result-failed':'';tr.append(td);});body.append(tr);});els.historyTable.append(body);}catch(error){toast('Could not load history',error.message,'error');}}
async function saveSettings(){try{state.settings=await api('/api/settings',jsonOptions('PUT',{max_batch_size:Number(els.maxBatchSize.value),default_throttle_ms:Number(els.defaultThrottle.value)}));toast('Settings saved','','success');}catch(error){toast('Could not save settings',error.message,'error');}}
async function createBackup(){try{const r=await api('/api/backup',{method:'POST'});toast('Backup created',r.backup,'success',8000);}catch(error){toast('Backup failed',error.message,'error');}}


const tourSteps=[
  {selector:'.workflow-strip',title:'Five simple steps',text:'Recipients, Message, Check, Delivery, Review. Use the step bar or the Continue button to move through the campaign.'},
  {selector:'#dropzone',title:'Start with recipients',text:'Drop in Excel or CSV here, or switch to Google Sheets. MailDesk will suggest the email and name columns.'},
  {selector:'.review-rail',title:'Keep the sheet and message together',text:'The live sheet stays beside the personalized message. Click a source row to inspect the matching message, and map reusable placeholders to any sheet column.'},
  {selector:'.nav-item[data-view="accounts"]',title:'Connect a sender when you need one',text:'Dry runs work without an account. Add Gmail or a browser sender only when you are ready to create drafts or send.'},
];
function startTour(){state.tourPreviousFocus=document.activeElement;setView('campaign');setStep(1);els.tourOverlay.classList.remove('is-hidden');els.tourOverlay.setAttribute('aria-hidden','false');showTourStep(0);}
function showTourStep(index){state.tourIndex=Math.max(0,Math.min(tourSteps.length-1,index));const step=tourSteps[state.tourIndex];els.tourStepLabel.textContent=`${state.tourIndex+1} of ${tourSteps.length}`;els.tourTitle.textContent=step.title;els.tourText.textContent=step.text;els.tourBackButton.disabled=state.tourIndex===0;els.tourNextButton.textContent=state.tourIndex===tourSteps.length-1?'Start':'Next';requestAnimationFrame(()=>{positionTour();els.tourNextButton.focus();});}
function positionTour(){if(els.tourOverlay.classList.contains('is-hidden'))return;const target=q(tourSteps[state.tourIndex].selector);if(!target)return;const rect=target.getBoundingClientRect(),pad=8;Object.assign(els.tourSpotlight.style,{left:`${Math.max(8,rect.left-pad)}px`,top:`${Math.max(8,rect.top-pad)}px`,width:`${Math.max(24,rect.width+pad*2)}px`,height:`${Math.max(24,rect.height+pad*2)}px`});const cardRect=els.tourCard.getBoundingClientRect();let left=Math.min(Math.max(16,rect.left),innerWidth-cardRect.width-16),top=rect.bottom+16;if(top+cardRect.height>innerHeight-16)top=rect.top-cardRect.height-16;if(top<16){top=Math.max(16,(innerHeight-cardRect.height)/2);left=Math.max(16,(innerWidth-cardRect.width)/2);}Object.assign(els.tourCard.style,{left:`${left}px`,top:`${top}px`});}
function finishTour(){localStorage.setItem(TOUR_STORAGE_KEY,'1');els.tourOverlay.classList.add('is-hidden');els.tourOverlay.setAttribute('aria-hidden','true');els.tourSpotlight.removeAttribute('style');els.tourCard.removeAttribute('style');if(state.tourPreviousFocus?.focus)state.tourPreviousFocus.focus();else els.startTourButton.focus();}

function saveUiState(){
  const data={mode:currentMode(),campaignName:els.campaignName.value,throttleMs:els.throttleMs.value,skipDuplicates:els.skipDuplicates.checked,browserSender:els.browserSender.value,gmailAccount:els.gmailAccount.value,sourceTab:state.sourceTab};
  localStorage.setItem('maildesk-ui-state',JSON.stringify(data));
}
function restoreUiState(){
  try{const data=JSON.parse(localStorage.getItem('maildesk-ui-state')||localStorage.getItem('mailmerge-ui-state')||'{}');if(data.mode){const radio=q(`input[name="mode"][value="${data.mode}"]`);if(radio)radio.checked=true;}if(data.campaignName)els.campaignName.value=data.campaignName;if(data.throttleMs)els.throttleMs.value=data.throttleMs;if(typeof data.skipDuplicates==='boolean')els.skipDuplicates.checked=data.skipDuplicates;if(data.browserSender&&state.browserSenders.some(x=>x.id===data.browserSender))els.browserSender.value=data.browserSender;if(data.gmailAccount&&state.gmailAccounts.some(x=>x.email===data.gmailAccount))els.gmailAccount.value=data.gmailAccount;if(data.sourceTab)setSourceTab(data.sourceTab);setStep(1);}catch{setStep(1);}
}

async function loadVersion(){try{const r=await api('/api/health');els.versionLabel.textContent=`v${r.version}`;}catch{els.versionLabel.textContent='';}}

function bindEvents(){
  window.addEventListener('beforeunload', saveUiState);
  qsa('.nav-item').forEach(b=>b.addEventListener('click',()=>setView(b.dataset.view)));qsa('.workflow-step').forEach(b=>b.addEventListener('click',()=>setStep(b.dataset.step)));qsa('.source-tab').forEach(b=>b.addEventListener('click',()=>setSourceTab(b.dataset.sourceTab)));qsa('.editor-tab').forEach(b=>b.addEventListener('click',()=>setEditorTab(b.dataset.editor)));
  els.nextStepButton.addEventListener('click',advanceStep);els.backStepButton.addEventListener('click',()=>setStep(state.step-1));
  els.sheetFile.addEventListener('change',()=>uploadSheet(els.sheetFile.files[0]));['dragenter','dragover'].forEach(ev=>els.dropzone.addEventListener(ev,e=>{e.preventDefault();els.dropzone.classList.add('is-dragging');}));['dragleave','drop'].forEach(ev=>els.dropzone.addEventListener(ev,e=>{e.preventDefault();els.dropzone.classList.remove('is-dragging');}));els.dropzone.addEventListener('drop',e=>{const f=e.dataTransfer.files[0];if(f)uploadSheet(f);});
  els.loadGoogleSheetButton.addEventListener('click',loadGoogleSheet);els.refreshGoogleSheetButton.addEventListener('click',refreshGoogleSheet);els.sheetSelect.addEventListener('change',()=>loadSheetPreview(true));els.headerRow.addEventListener('change',()=>loadSheetPreview(true));[els.toColumn,els.nameColumn,els.ccColumn,els.bccColumn,els.attachmentColumn,els.sortColumn,els.sortDirection].forEach(x=>x.addEventListener('change',scheduleRender));els.filterColumn.addEventListener('change',()=>{els.filterValue.disabled=!els.filterColumn.value||els.filterOperator.value==='not_empty';scheduleRender();});els.filterOperator.addEventListener('change',()=>{els.filterValue.disabled=els.filterOperator.value==='not_empty'||!els.filterColumn.value;scheduleRender();});[els.filterValue,els.rowLimit].forEach(x=>x.addEventListener('input',scheduleRender));els.trimValues.addEventListener('change',scheduleRender);els.selectVisibleButton.addEventListener('click',()=>{state.previewRows.forEach(r=>state.selectedRows.add(r._row));renderSheetPreview();updateSelectionSummary();scheduleRender();});els.clearVisibleButton.addEventListener('click',()=>{state.previewRows.forEach(r=>state.selectedRows.delete(r._row));renderSheetPreview();updateSelectionSummary();scheduleRender();});
  els.templateSelect.addEventListener('change',loadTemplateIntoForm);els.autoMapPlaceholdersButton.addEventListener('click',autoMapPlaceholders);els.newTemplateButton.addEventListener('click',newTemplate);els.saveTemplateButton.addEventListener('click',()=>saveTemplate().catch(e=>toast('Could not save template',e.message,'error')));els.deleteTemplateButton.addEventListener('click',()=>deleteTemplate().catch(e=>toast('Could not delete template',e.message,'error')));[els.subjectTemplate,els.bodyTemplate,els.ccTemplate,els.bccTemplate].forEach(x=>{x.addEventListener('focus',()=>state.activeEditor=x);x.addEventListener('input',scheduleRender);});[els.bodyHtmlEditor,els.signatureHtmlEditor].forEach(x=>{x.addEventListener('focus',()=>state.activeEditor=x);x.addEventListener('input',scheduleRender);});qsa('[data-rich]').forEach(b=>b.addEventListener('click',()=>{document.execCommand(b.dataset.rich,false,null);els.bodyHtmlEditor.focus();scheduleRender();}));els.clearFormattingButton.addEventListener('click',()=>{document.execCommand('removeFormat',false,null);scheduleRender();});els.newSnippetButton.addEventListener('click',()=>els.snippetDialog.showModal());els.saveSnippetDialogButton.addEventListener('click',saveSnippetFromDialog);els.attachmentFile.addEventListener('change',()=>uploadAttachments(els.attachmentFile.files));els.renderButton.addEventListener('click',()=>renderCampaign(true));
  qsa('input[name="mode"]').forEach(x=>x.addEventListener('change',updateModeUI));els.browserSender.addEventListener('change',()=>{updateBrowserSenderSummary();updateFinalSummary();});els.gmailAccount.addEventListener('change',updateFinalSummary);els.throttleMs.addEventListener('input',()=>{els.throttleMs.dataset.touched='1';});els.scheduleAt.addEventListener('change',updateFinalSummary);els.confirmText.addEventListener('input',updateFinalSummary);els.queueCampaignButton.addEventListener('click',queueCampaign);els.exportReviewButton.addEventListener('click',exportReviewCsv);
  els.prevMessage.addEventListener('click',()=>{state.messageIndex=Math.max(0,state.messageIndex-1);renderReview();});els.nextMessage.addEventListener('click',()=>{state.messageIndex=Math.min((state.rendered?.messages.length||1)-1,state.messageIndex+1);renderReview();});[els.reviewTo,els.reviewCc,els.reviewBcc,els.reviewSubject,els.reviewBody].forEach(x=>x.addEventListener('change',commitReviewEdit));els.reviewBody.addEventListener('input',handleReviewBodyInput);
  els.oauthFile.addEventListener('change',()=>connectGoogle(els.oauthFile.files[0]));els.browserProfile.addEventListener('change',()=>{updateProfileEmailHints();selectFirstDetectedBrowserAccount();});els.rescanBrowserProfilesButton.addEventListener('click',rescanBrowserProfiles);els.newBrowserSenderButton.addEventListener('click',resetBrowserSenderForm);els.saveBrowserSenderButton.addEventListener('click',saveBrowserSender);els.verifySelectedBrowserButton.addEventListener('click',()=>{if(els.browserSender.value)startVerifyBrowserSender(els.browserSender.value);else setView('accounts');});els.confirmBrowserVerifiedButton.addEventListener('click',confirmBrowserVerified);els.refreshQueueButton.addEventListener('click',refreshQueue);els.refreshHistoryButton.addEventListener('click',refreshHistory);els.saveSettingsButton.addEventListener('click',saveSettings);els.backupButton.addEventListener('click',createBackup);
  els.startTourButton.addEventListener('click',startTour);els.skipTourButton.addEventListener('click',finishTour);els.tourBackButton.addEventListener('click',()=>showTourStep(state.tourIndex-1));els.tourNextButton.addEventListener('click',()=>state.tourIndex===tourSteps.length-1?finishTour():showTourStep(state.tourIndex+1));window.addEventListener('resize',positionTour);window.addEventListener('scroll',positionTour,true);document.addEventListener('keydown',event=>{if(event.key==='Escape'&&!els.tourOverlay.classList.contains('is-hidden'))finishTour();});
}

async function init(){bindEvents();await loadVersion();try{await Promise.all([loadTemplates(),refreshAccountsAndBrowsers(),refreshQueue()]);}catch(error){toast('Initialization problem',error.message,'error');}restoreUiState();updateModeUI();if(!state.step)setStep(1);if(!localStorage.getItem(TOUR_STORAGE_KEY)&&!localStorage.getItem('maildesk-onboarded')&&!localStorage.getItem('mailmerge-onboarded'))requestAnimationFrame(startTour);}
init();
