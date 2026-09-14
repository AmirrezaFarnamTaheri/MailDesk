from __future__ import annotations

import re
import subprocess
from pathlib import Path

EXPECTED = {
    "mailmerge_app/static/app.js": "70ad81b18e88b42cc260c2a5e18e89c6bd9fcc36",
    "mailmerge_app/static/index.html": "98981e26e70a2deae316560f320ed3653394e190",
    "mailmerge_app/static/app.css": "41db6d65571e918dae637dc73bec48b62a0ca42f",
    "tests/test_frontend_integrity.py": "1ed74d160dbb8c32f9eb5d2c38c71b43541d248b",
}
for path, expected in EXPECTED.items():
    actual = subprocess.check_output(["git", "hash-object", path], text=True).strip()
    if actual != expected:
        raise RuntimeError(f"{path} changed: {actual} != {expected}")


def replace_once(path: str, old: str, new: str) -> None:
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    if text.count(old) != 1:
        raise RuntimeError(f"Expected one target in {path}, found {text.count(old)}")
    p.write_text(text.replace(old, new, 1), encoding="utf-8")


def sub_once(path: str, pattern: str, replacement: str) -> None:
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    updated, count = re.subn(pattern, lambda _m: replacement, text, count=1, flags=re.S)
    if count != 1:
        raise RuntimeError(f"Expected one regex target in {path}, found {count}")
    p.write_text(updated, encoding="utf-8")


# Message step: visible placeholder-to-column mapping.
replace_once(
    "mailmerge_app/static/index.html",
    '<div class="panel-head"><div><h2>Message</h2><p>Write once and insert spreadsheet columns where you want personalization.</p></div><div class="panel-actions"><button class="button ghost small" id="newTemplateButton">New</button><button class="button secondary small" id="saveTemplateButton">Save template</button></div></div>',
    '<div class="panel-head"><div><h2>Message</h2><p>Write with reusable placeholders, then map them to columns in this sheet.</p></div><div class="panel-actions"><button class="button ghost small" id="newTemplateButton">New</button><button class="button secondary small" id="saveTemplateButton">Save template</button></div></div>',
)
replace_once(
    "mailmerge_app/static/index.html",
    '<div class="placeholder-section"><div class="field-label-row"><span>Insert placeholder</span><span class="hint">Defaults: <code>{{Name|there}}</code> · Conditional: <code>{{#if Link}}…{{/if}}</code></span></div><div class="placeholder-list" id="placeholderList"><span class="empty-inline">Load a source to see columns.</span></div></div>',
    '''<div class="placeholder-mapper">
                    <div class="placeholder-mapper-head">
                      <div><strong>Placeholder mapping</strong><span>Choose which sheet column supplies each reusable placeholder.</span></div>
                      <button type="button" class="button secondary small" id="autoMapPlaceholdersButton">Auto-match</button>
                    </div>
                    <div class="placeholder-mapping-list" id="placeholderMappingList"><div class="empty-inline">Add a placeholder to the message to map it.</div></div>
                  </div>
                  <div class="placeholder-section"><div class="field-label-row"><span>Insert placeholder</span><span class="hint">Defaults: <code>{{Name|there}}</code> · Conditional: <code>{{#if Link}}…{{/if}}</code></span></div><div class="placeholder-list" id="placeholderList"><span class="empty-inline">Load a source to see columns.</span></div></div>''',
)

# Live source sheet in the persistent right rail.
replace_once(
    "mailmerge_app/static/index.html",
    '''            </div>
          </aside>
        </div>
      </section>''',
    '''            </div>
            <div class="review-card live-sheet-card" id="liveSheetCard">
              <div class="review-head"><div><span class="eyebrow">Live sheet</span><strong id="liveSheetSummary">No spreadsheet loaded</strong></div></div>
              <div class="live-sheet-empty" id="liveSheetEmpty">Load a spreadsheet to keep source rows visible while you write and review.</div>
              <div class="live-sheet-scroll is-hidden" id="liveSheetScroll"><table class="live-sheet-table" id="liveSheetTable"></table></div>
            </div>
          </aside>
        </div>
      </section>''',
)

# Browser sender form: detected accounts first, manual entry only as fallback.
sub_once(
    "mailmerge_app/static/index.html",
    r'<div class="browser-route-form" id="browserRouteForm">.*?</div>\n              <div id="browserSenderList"',
    '''<div class="browser-route-form" id="browserRouteForm">
                <input id="browserSenderId" type="hidden">
                <div class="field-grid two">
                  <label class="field"><span>Label</span><input id="browserSenderLabel" placeholder="Work Gmail"></label>
                  <label class="field"><span>Browser profile</span><select id="browserProfile"></select></label>
                </div>
                <div class="detected-browser-block">
                  <div class="field-label-row"><span>Detected Gmail accounts</span><button type="button" class="button ghost small" id="rescanBrowserProfilesButton">Rescan browsers</button></div>
                  <div class="detected-browser-accounts" id="detectedBrowserAccounts"></div>
                  <p class="hint" id="browserDetectionHint">Choose a browser profile to inspect its cached signed-in Gmail accounts.</p>
                </div>
                <details class="advanced compact-advanced" id="manualBrowserSenderOptions">
                  <summary>Can’t see the account?</summary>
                  <div class="field-grid two">
                    <label class="field"><span>Account index</span><input id="gmailSlot" type="number" min="0" max="99" value="0"></label>
                    <label class="field"><span>Expected email</span><input id="browserExpectedEmail" type="email" list="profileEmails" placeholder="work@example.com"><datalist id="profileEmails"></datalist></label>
                  </div>
                  <p class="hint">Use this fallback when Gmail’s cached account list is unavailable. Account 0 is the first signed-in Gmail account in that browser profile.</p>
                </details>
                <div class="button-row compact-top"><button class="button primary" id="saveBrowserSenderButton">Save sender</button></div>
              </div>
              <div id="browserSenderList"''',
)

# Element registry and state.
replace_once("mailmerge_app/static/app.js", "'templateSelect','templateName','subjectTemplate','bodyTemplate','bodyHtmlEditor','signatureHtmlEditor','placeholderList','snippetList','attachmentList','attachmentFile','newSnippetButton','newTemplateButton','saveTemplateButton','deleteTemplateButton','clearFormattingButton',", "'templateSelect','templateName','subjectTemplate','bodyTemplate','bodyHtmlEditor','signatureHtmlEditor','placeholderList','placeholderMappingList','autoMapPlaceholdersButton','snippetList','attachmentList','attachmentFile','newSnippetButton','newTemplateButton','saveTemplateButton','deleteTemplateButton','clearFormattingButton',")
replace_once("mailmerge_app/static/app.js", "'reviewPosition','prevMessage','nextMessage','reviewEmpty','reviewContent','reviewStatus','reviewTo','reviewCc','reviewBcc','reviewSubject','reviewBody','htmlPreviewWrap','htmlPreview','reviewMeta',", "'reviewPosition','prevMessage','nextMessage','reviewEmpty','reviewContent','reviewStatus','reviewTo','reviewCc','reviewBcc','reviewSubject','reviewBody','htmlPreviewWrap','htmlPreview','reviewMeta','liveSheetCard','liveSheetSummary','liveSheetEmpty','liveSheetScroll','liveSheetTable',")
replace_once("mailmerge_app/static/app.js", "'queueList','refreshQueueButton','oauthFile','includeSheetsScope','accountList','newBrowserSenderButton','browserRouteForm','browserSenderId','browserSenderLabel','browserProfile','gmailSlot','browserExpectedEmail','profileEmails','saveBrowserSenderButton','browserSenderList','maxBatchSize','defaultThrottle','saveSettingsButton','backupButton',", "'queueList','refreshQueueButton','oauthFile','includeSheetsScope','accountList','newBrowserSenderButton','browserRouteForm','browserSenderId','browserSenderLabel','browserProfile','gmailSlot','browserExpectedEmail','profileEmails','detectedBrowserAccounts','browserDetectionHint','rescanBrowserProfilesButton','manualBrowserSenderOptions','saveBrowserSenderButton','browserSenderList','maxBatchSize','defaultThrottle','saveSettingsButton','backupButton',")
replace_once("mailmerge_app/static/app.js", "  importId: '', source: null, headers: [], previewRows: [], allRowNumbers: [], selectedRows: new Set(), rowOverrides: {}, suggestions: {},", "  importId: '', source: null, headers: [], previewRows: [], allRowNumbers: [], selectedRows: new Set(), rowOverrides: {}, suggestions: {}, placeholderMappings: {}, liveSheetRow: '',")
replace_once("mailmerge_app/static/app.js", "clearTimeout(state.renderTimer); state.importId=result.import_id; state.source=result; state.rowOverrides={}; state.selectedRows=new Set(); state.headers=[]; state.previewRows=[]; state.allRowNumbers=[]; invalidateReview({clearRendered:true});", "clearTimeout(state.renderTimer); state.importId=result.import_id; state.source=result; state.rowOverrides={}; state.selectedRows=new Set(); state.headers=[]; state.previewRows=[]; state.allRowNumbers=[]; state.placeholderMappings={}; state.liveSheetRow=''; invalidateReview({clearRendered:true});")

# Placeholder model and mapping UI.
sub_once(
    "mailmerge_app/static/app.js",
    r'function renderPlaceholders\(\)\{.*?\}\nfunction insertIntoActive',
    r'''function templatePlaceholderInfo(){
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
function insertIntoActive''',
)

replace_once("mailmerge_app/static/app.js", "trim_values:els.trimValues.checked};}", "trim_values:els.trimValues.checked,placeholder_mappings:Object.fromEntries(Object.entries(state.placeholderMappings).filter(([,column])=>column))};}")
replace_once("mailmerge_app/static/app.js", "function scheduleRender(){\n  clearTimeout(state.renderTimer);invalidateReview();", "function scheduleRender({syncMappings=true}={}){\n  if(syncMappings)syncPlaceholderMappings();renderLiveSheet();\n  clearTimeout(state.renderTimer);invalidateReview();")

# Live spreadsheet renderer.
replace_once(
    "mailmerge_app/static/app.js",
    "function updateSelectionSummary(){els.selectionSummary.textContent=state.selectedRows.size===state.allRowNumbers.length?' · all selected':` · ${state.selectedRows.size} selected`;}",
    '''function updateSelectionSummary(){els.selectionSummary.textContent=state.selectedRows.size===state.allRowNumbers.length?' · all selected':` · ${state.selectedRows.size} selected`;}
function renderLiveSheet(){
  if(!state.previewRows.length||!state.headers.length){els.liveSheetSummary.textContent='No spreadsheet loaded';els.liveSheetEmpty.classList.remove('is-hidden');els.liveSheetScroll.classList.add('is-hidden');els.liveSheetTable.innerHTML='';return;}
  const currentRendered=state.rendered?.messages?.[state.messageIndex];const activeRow=String(state.liveSheetRow||currentRendered?.row_number||state.previewRows[0]._row||'');state.liveSheetSummary.textContent=`${state.source?.filename||'Spreadsheet'} · ${state.previewRows.length}${state.allRowNumbers.length>state.previewRows.length?` of ${state.allRowNumbers.length}`:''} rows shown`;els.liveSheetEmpty.classList.add('is-hidden');els.liveSheetScroll.classList.remove('is-hidden');els.liveSheetTable.innerHTML='';
  const thead=document.createElement('thead'),head=document.createElement('tr');['Row',...state.headers].forEach(label=>{const th=document.createElement('th');th.textContent=label;head.append(th);});thead.append(head);els.liveSheetTable.append(thead);const tbody=document.createElement('tbody');state.previewRows.forEach(row=>{const tr=document.createElement('tr');tr.dataset.row=String(row._row);tr.classList.toggle('is-active',String(row._row)===activeRow);const rowCell=document.createElement('td');rowCell.textContent=row._row;tr.append(rowCell);state.headers.forEach(header=>{const td=document.createElement('td');td.textContent=sourceCell(row,header);td.title=td.textContent;tr.append(td);});tr.addEventListener('click',()=>{state.liveSheetRow=String(row._row);const index=state.rendered?.messages?.findIndex(message=>String(message.row_number)===String(row._row))??-1;if(index>=0){state.messageIndex=index;renderReview();}else{renderLiveSheet();renderPlaceholderMappings();}});tbody.append(tr);});els.liveSheetTable.append(tbody);
}''',
)
replace_once("mailmerge_app/static/app.js", "  const names=(m.attachments||[]).map(id=>state.attachments.find(a=>a.id===id)?.name||id);els.reviewMeta.innerHTML=`<span>${esc(m.display_name||'')}</span><span>${names.length?`${names.length} attachment${names.length===1?'':'s'}: ${esc(names.join(', '))}`:'No attachments'}</span>`;\n}", "  const names=(m.attachments||[]).map(id=>state.attachments.find(a=>a.id===id)?.name||id);els.reviewMeta.innerHTML=`<span>${esc(m.display_name||'')}</span><span>${names.length?`${names.length} attachment${names.length===1?'':'s'}: ${esc(names.join(', '))}`:'No attachments'}</span>`;state.liveSheetRow=String(m.row_number);renderLiveSheet();renderPlaceholderMappings();\n}")

# Browser account cards and forced rescan.
replace_once("mailmerge_app/static/app.js", "async function refreshAccountsAndBrowsers(){\n  try{const [accounts,profiles,senders,settings]=await Promise.all([api('/api/accounts'),api('/api/browser-profiles'),api('/api/browser-senders'),api('/api/settings')]);", "async function refreshAccountsAndBrowsers(forceBrowserRefresh=false){\n  try{const profileUrl=forceBrowserRefresh?'/api/browser-profiles?refresh=true':'/api/browser-profiles';const [accounts,profiles,senders,settings]=await Promise.all([api('/api/accounts'),api(profileUrl),api('/api/browser-senders'),api('/api/settings')]);")
sub_once(
    "mailmerge_app/static/app.js",
    r'function renderBrowserProfiles\(\)\{.*?\}\nfunction updateProfileEmailHints\(\)\{.*?\}\nfunction renderBrowserSenders',
    r'''function renderBrowserProfiles(){const prev=els.browserProfile.value;els.browserProfile.innerHTML='';state.browserProfiles.forEach(p=>{const o=document.createElement('option');o.value=p.profile_id;o.textContent=`${p.browser_name} · ${p.profile_name}${p.primary_email?` · ${p.primary_email}`:''}`;els.browserProfile.append(o);});if(state.browserProfiles.some(p=>p.profile_id===prev))els.browserProfile.value=prev;updateProfileEmailHints();}
function updateProfileEmailHints(){const p=state.browserProfiles.find(x=>x.profile_id===els.browserProfile.value);els.profileEmails.innerHTML='';(p?.emails||[]).forEach(email=>{const o=document.createElement('option');o.value=email;els.profileEmails.append(o);});renderDetectedBrowserAccounts();}
function renderDetectedBrowserAccounts(){const p=state.browserProfiles.find(x=>x.profile_id===els.browserProfile.value);els.detectedBrowserAccounts.innerHTML='';const accounts=p?.gmail_accounts||[];if(!p){els.browserDetectionHint.textContent='No browser profile is available.';return;}if(!accounts.length){els.detectedBrowserAccounts.innerHTML='<div class="empty-inline">No ordered Gmail session accounts found in this profile.</div>';els.browserDetectionHint.textContent=(p.emails||[]).length?'MailDesk found profile email hints, but not enough browser-session data to determine Gmail account indexes. Use the manual fallback below.':'Sign in to Gmail in this browser profile, then click Rescan browsers. You can also use the manual fallback.';return;}els.browserDetectionHint.textContent='Detected from the browser’s cached Google session. Select an account, then verify it once in Gmail before use.';accounts.forEach(account=>{const button=document.createElement('button');button.type='button';button.className='detected-browser-account';button.classList.toggle('is-selected',Number(els.gmailSlot.value)===Number(account.slot)&&els.browserExpectedEmail.value.toLocaleLowerCase()===String(account.email).toLocaleLowerCase());button.innerHTML=`<span class="detected-account-index">${account.slot}</span><span><strong>${esc(account.email)}</strong><small>${account.valid===false?'Session may need sign-in':'Signed-in Gmail account'} · ${esc(p.browser_name)} ${esc(p.profile_name)}</small></span>`;button.addEventListener('click',()=>{els.gmailSlot.value=account.slot;els.browserExpectedEmail.value=account.email;if(!els.browserSenderLabel.value.trim())els.browserSenderLabel.value=account.email;renderDetectedBrowserAccounts();});els.detectedBrowserAccounts.append(button);});}
function selectFirstDetectedBrowserAccount(){const p=state.browserProfiles.find(x=>x.profile_id===els.browserProfile.value);const first=p?.gmail_accounts?.[0];if(first){els.gmailSlot.value=first.slot;els.browserExpectedEmail.value=first.email;}else{els.gmailSlot.value=0;els.browserExpectedEmail.value='';}renderDetectedBrowserAccounts();}
async function rescanBrowserProfiles(){const label=els.rescanBrowserProfilesButton.textContent;els.rescanBrowserProfilesButton.disabled=true;els.rescanBrowserProfilesButton.textContent='Scanning…';try{await refreshAccountsAndBrowsers(true);toast('Browsers rescanned','Detected Gmail accounts were refreshed.','success');}catch(error){toast('Browser scan failed',error.message,'error');}finally{els.rescanBrowserProfilesButton.disabled=false;els.rescanBrowserProfilesButton.textContent=label;}}
function renderBrowserSenders''',
)
replace_once("mailmerge_app/static/app.js", "function editBrowserSender(s){els.browserSenderId.value=s.id;els.browserSenderLabel.value=s.label;els.gmailSlot.value=s.gmail_slot;els.browserExpectedEmail.value=s.expected_email;const p=state.browserProfiles.find(x=>x.browser_id===s.browser_id&&x.profile_dir===s.profile_dir);if(p)els.browserProfile.value=p.profile_id;updateProfileEmailHints();window.scrollTo({top:0,behavior:'smooth'});}", "function editBrowserSender(s){els.browserSenderId.value=s.id;els.browserSenderLabel.value=s.label;els.gmailSlot.value=s.gmail_slot;els.browserExpectedEmail.value=s.expected_email;const p=state.browserProfiles.find(x=>x.browser_id===s.browser_id&&x.profile_dir===s.profile_dir);if(p)els.browserProfile.value=p.profile_id;updateProfileEmailHints();renderDetectedBrowserAccounts();window.scrollTo({top:0,behavior:'smooth'});}")
replace_once("mailmerge_app/static/app.js", "function resetBrowserSenderForm(){els.browserSenderId.value='';els.browserSenderLabel.value='';els.gmailSlot.value=0;els.browserExpectedEmail.value='';if(state.browserProfiles[0])els.browserProfile.value=state.browserProfiles[0].profile_id;updateProfileEmailHints();}", "function resetBrowserSenderForm(){els.browserSenderId.value='';els.browserSenderLabel.value='';els.gmailSlot.value=0;els.browserExpectedEmail.value='';if(state.browserProfiles[0])els.browserProfile.value=state.browserProfiles[0].profile_id;updateProfileEmailHints();selectFirstDetectedBrowserAccount();}")

replace_once("mailmerge_app/static/app.js", "els.templateSelect.addEventListener('change',loadTemplateIntoForm);els.newTemplateButton.addEventListener('click',newTemplate);", "els.templateSelect.addEventListener('change',loadTemplateIntoForm);els.autoMapPlaceholdersButton.addEventListener('click',autoMapPlaceholders);els.newTemplateButton.addEventListener('click',newTemplate);")
replace_once("mailmerge_app/static/app.js", "els.oauthFile.addEventListener('change',()=>connectGoogle(els.oauthFile.files[0]));els.browserProfile.addEventListener('change',updateProfileEmailHints);els.newBrowserSenderButton.addEventListener('click',resetBrowserSenderForm);", "els.oauthFile.addEventListener('change',()=>connectGoogle(els.oauthFile.files[0]));els.browserProfile.addEventListener('change',()=>{updateProfileEmailHints();selectFirstDetectedBrowserAccount();});els.rescanBrowserProfilesButton.addEventListener('click',rescanBrowserProfiles);els.newBrowserSenderButton.addEventListener('click',resetBrowserSenderForm);")
replace_once("mailmerge_app/static/app.js", "  {selector:'.review-card',title:'Preview the personalized result',text:'After you check messages, use this panel to move through recipients and make a last edit when needed.'},", "  {selector:'.review-rail',title:'Keep the sheet and message together',text:'The live sheet stays beside the personalized message. Click a source row to inspect the matching message, and map reusable placeholders to any sheet column.'},")

# CSS for the workbench.
css = '''\n\n/* Personalization workbench */\n.placeholder-mapper{margin-top:16px;border:1px solid var(--line);border-radius:12px;background:#fbfcfd;overflow:hidden}.placeholder-mapper-head{padding:11px 12px;border-bottom:1px solid var(--line);display:flex;align-items:center;justify-content:space-between;gap:12px}.placeholder-mapper-head strong{display:block;font-size:12px}.placeholder-mapper-head span{display:block;font-size:10.5px;color:var(--muted);margin-top:2px}.placeholder-mapping-list{display:grid}.placeholder-map-row{display:grid;grid-template-columns:minmax(110px,.8fr) minmax(140px,1.2fr) minmax(100px,1fr);gap:9px;align-items:center;padding:9px 11px;border-top:1px solid #edf0f3}.placeholder-map-row:first-child{border-top:0}.placeholder-map-token{display:flex;align-items:center;gap:6px;min-width:0}.placeholder-map-token code{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.placeholder-map-token span{font-size:9px;color:var(--muted);text-transform:uppercase;letter-spacing:.05em}.placeholder-map-select{width:100%;min-width:0;border:1px solid var(--line-strong);border-radius:8px;background:#fff;padding:7px 8px;font-size:11px}.placeholder-map-built-in{font-size:11px;color:var(--muted)}.placeholder-map-sample{font-size:10.5px;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}\n.campaign-grid{grid-template-columns:minmax(0,1fr) minmax(360px,420px)}.live-sheet-card{min-width:0}.live-sheet-empty{padding:22px 16px;color:var(--muted);font-size:11.5px;line-height:1.45}.live-sheet-scroll{max-height:300px;overflow:auto}.live-sheet-table{border-collapse:collapse;width:max-content;min-width:100%;font-size:10.5px}.live-sheet-table th{position:sticky;top:0;z-index:2;background:#f5f7f9;color:#596673;text-align:left;font-weight:700}.live-sheet-table th,.live-sheet-table td{padding:7px 8px;border-bottom:1px solid #edf0f3;border-right:1px solid #f0f2f4;white-space:nowrap;max-width:180px;overflow:hidden;text-overflow:ellipsis}.live-sheet-table tbody tr{cursor:pointer}.live-sheet-table tbody tr:hover td{background:#f7f9fd}.live-sheet-table tbody tr.is-active td{background:#eef3ff}.live-sheet-table tbody tr.is-active td:first-child{box-shadow:inset 3px 0 0 var(--accent)}\n.detected-browser-block{margin-top:16px}.detected-browser-accounts{display:grid;gap:7px}.detected-browser-account{width:100%;border:1px solid var(--line);border-radius:11px;background:#fff;padding:9px 10px;display:grid;grid-template-columns:30px 1fr;gap:9px;text-align:left;align-items:center}.detected-browser-account:hover{border-color:#a9b8ca;background:#fafcff}.detected-browser-account.is-selected{border-color:#86a2eb;background:#f5f8ff;box-shadow:0 0 0 2px #2358d70d}.detected-account-index{width:28px;height:28px;border-radius:8px;display:grid;place-items:center;background:#edf2f8;font-weight:760;font-size:11px}.detected-browser-account strong{display:block;font-size:11.5px}.detected-browser-account small{display:block;margin-top:2px;color:var(--muted);font-size:10px}.detected-browser-block>.hint{display:block;margin-top:8px}\n@media(max-width:1100px){.campaign-grid{grid-template-columns:1fr}.live-sheet-scroll{max-height:340px}}@media(max-width:820px){.placeholder-map-row{grid-template-columns:1fr}.placeholder-map-sample{white-space:normal}}\n'''
Path("mailmerge_app/static/app.css").write_text(Path("mailmerge_app/static/app.css").read_text(encoding="utf-8") + css, encoding="utf-8")

replace_once(
    "tests/test_frontend_integrity.py",
    '\n\nif __name__ == "__main__":\n    unittest.main()\n',
    '''\n    def test_placeholder_mapping_ui_is_wired_to_render_payload(self):\n        self.assertIn('id="placeholderMappingList"', INDEX_HTML)\n        self.assertIn('id="autoMapPlaceholdersButton"', INDEX_HTML)\n        self.assertIn('templatePlaceholderInfo', APP_JS)\n        self.assertIn('placeholder_mappings:Object.fromEntries', APP_JS)\n\n    def test_live_sheet_stays_beside_message_preview(self):\n        self.assertIn('id="liveSheetCard"', INDEX_HTML)\n        self.assertIn('id="liveSheetTable"', INDEX_HTML)\n        self.assertIn('function renderLiveSheet()', APP_JS)\n        self.assertIn("findIndex(message=>String(message.row_number)===String(row._row))", APP_JS)\n\n    def test_browser_sender_setup_prefers_detected_accounts(self):\n        self.assertIn('id="detectedBrowserAccounts"', INDEX_HTML)\n        self.assertIn('id="rescanBrowserProfilesButton"', INDEX_HTML)\n        self.assertIn('/api/browser-profiles?refresh=true', APP_JS)\n        self.assertIn('p?.gmail_accounts||[]', APP_JS)\n        self.assertIn('Can’t see the account?', INDEX_HTML)\n\n\nif __name__ == "__main__":\n    unittest.main()\n''',
)

print("placeholder mapping, live sheet, and browser account UI applied")
