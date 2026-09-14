from __future__ import annotations

from pathlib import Path
import re


def replace_once(path: str, old: str, new: str) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    if old not in text:
        raise SystemExit(f"missing anchor in {path}: {old[:100]!r}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


def regex_once(path: str, pattern: str, replacement: str) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    updated, count = re.subn(pattern, lambda _match: replacement, text, count=1, flags=re.S)
    if count != 1:
        raise SystemExit(f"expected one regex match in {path}, got {count}: {pattern[:100]!r}")
    target.write_text(updated, encoding="utf-8")


# Combine placeholder creation and mapping into one guided personalization workbench.
regex_once(
    "mailmerge_app/static/index.html",
    r'''                  <div class="placeholder-mapper">.*?                  <div class="split-section">''',
    '''                  <div class="personalization-workbench">
                    <div class="personalization-builder">
                      <div class="personalization-builder-head">
                        <div><span class="section-kicker">Personalization builder</span><strong>Create a reusable placeholder</strong><span>Name it once, choose where its value comes from, and insert it at the current cursor.</span></div>
                        <span class="insert-target" id="placeholderInsertTarget">Insert into · Message</span>
                      </div>
                      <div class="placeholder-builder-grid">
                        <label class="field placeholder-builder-field"><span><b class="builder-step">1</b> Placeholder name</span><input id="placeholderNameInput" type="text" maxlength="80" autocomplete="off" placeholder="FirstName"></label>
                        <label class="field placeholder-builder-field"><span><b class="builder-step">2</b> Fill from</span><select id="placeholderSourceSelect"><option value="">Choose a source…</option></select></label>
                        <label class="field placeholder-builder-field"><span><b class="builder-step">3</b> Fallback if blank <em>optional</em></span><input id="placeholderFallbackInput" type="text" maxlength="240" autocomplete="off" placeholder="there"></label>
                      </div>
                      <div class="placeholder-builder-preview">
                        <div class="builder-preview-cell"><span>Token</span><code id="placeholderTokenPreview">{{Placeholder}}</code></div>
                        <div class="builder-preview-cell sample"><span>Sample value</span><strong id="placeholderSamplePreview">Choose a source</strong></div>
                        <div class="placeholder-builder-actions"><button type="button" class="button primary" id="insertPlaceholderButton" disabled>Insert placeholder</button><button type="button" class="button secondary" id="insertConditionalButton" disabled>Insert condition</button></div>
                      </div>
                      <div class="placeholder-quick-source">
                        <div><span>Quick source</span><small>Pick a column to prefill the builder. You can rename the placeholder before inserting it.</small></div>
                        <div class="placeholder-list" id="placeholderList"><span class="empty-inline">Load a source to see columns.</span></div>
                      </div>
                    </div>
                    <div class="placeholder-mapper">
                      <div class="placeholder-mapper-head">
                        <div><strong>Used placeholders</strong><span id="placeholderMappingSummary">No placeholders in this template yet.</span></div>
                        <button type="button" class="button secondary small" id="autoMapPlaceholdersButton">Auto-match columns</button>
                      </div>
                      <div class="placeholder-mapping-list" id="placeholderMappingList"><div class="empty-inline placeholder-empty-state">Create or type a placeholder to map it.</div></div>
                    </div>
                  </div>
                  <div class="split-section">''',
)

replace_once(
    "mailmerge_app/static/app.js",
    "  'templateSelect','templateName','subjectTemplate','bodyTemplate','bodyHtmlEditor','signatureHtmlEditor','placeholderList','placeholderMappingList','autoMapPlaceholdersButton','snippetList','attachmentList','attachmentFile','newSnippetButton','newTemplateButton','saveTemplateButton','deleteTemplateButton','clearFormattingButton',\n",
    "  'templateSelect','templateName','subjectTemplate','bodyTemplate','bodyHtmlEditor','signatureHtmlEditor','placeholderList','placeholderMappingList','placeholderMappingSummary','autoMapPlaceholdersButton','placeholderNameInput','placeholderSourceSelect','placeholderFallbackInput','placeholderTokenPreview','placeholderSamplePreview','placeholderInsertTarget','insertPlaceholderButton','insertConditionalButton','snippetList','attachmentList','attachmentFile','newSnippetButton','newTemplateButton','saveTemplateButton','deleteTemplateButton','clearFormattingButton',\n",
)
replace_once(
    "mailmerge_app/static/app.js",
    "  importId: '', source: null, headers: [], previewRows: [], allRowNumbers: [], selectedRows: new Set(), rowOverrides: {}, suggestions: {}, placeholderMappings: {}, liveSheetRow: '',\n",
    "  importId: '', source: null, headers: [], previewRows: [], allRowNumbers: [], selectedRows: new Set(), rowOverrides: {}, suggestions: {}, placeholderMappings: {}, placeholderMappingLocked: new Set(), liveSheetRow: '',\n",
)
replace_once(
    "mailmerge_app/static/app.js",
    "  clearTimeout(state.renderTimer); state.importId=result.import_id; state.source=result; state.rowOverrides={}; state.selectedRows=new Set(); state.headers=[]; state.previewRows=[]; state.allRowNumbers=[]; state.placeholderMappings={}; state.liveSheetRow=''; invalidateReview({clearRendered:true});\n",
    "  clearTimeout(state.renderTimer); state.importId=result.import_id; state.source=result; state.rowOverrides={}; state.selectedRows=new Set(); state.headers=[]; state.previewRows=[]; state.allRowNumbers=[]; state.placeholderMappings={}; state.placeholderMappingLocked=new Set(); state.liveSheetRow=''; invalidateReview({clearRendered:true});\n",
)

js_replacement = r'''function templatePlaceholderInfo(){
  const fields=[els.subjectTemplate.value,els.bodyTemplate.value,els.bodyHtmlEditor.innerHTML,els.signatureHtmlEditor.innerHTML,els.ccTemplate.value,els.bccTemplate.value];const found=new Map();
  const add=(expression,conditional=false)=>{const parts=String(expression||'').split('|');const key=(parts.shift()||'').trim();if(!key)return;const fallback=parts.join('|').trim();const current=found.get(key)||{key,fallback:'',conditional:false,plain:false};if(fallback&&!current.fallback)current.fallback=fallback;current.conditional=current.conditional||conditional;current.plain=current.plain||!conditional;found.set(key,current);};
  fields.forEach(text=>{let match;const condition=/{{\s*#if\s+([^{}]+?)\s*}}/g;while((match=condition.exec(text||'')))add(match[1],true);const plain=/{{\s*(?!#if\b|\/if\b)([^{}]+?)\s*}}/g;while((match=plain.exec(text||'')))add(match[1],false);});return [...found.values()];
}
function normalizedColumnKey(value){return String(value||'').trim().toLocaleLowerCase().replace(/[\s_.-]+/g,'');}
function guessPlaceholderColumn(key){const lower=String(key||'').toLocaleLowerCase();if(lower==='name'&&state.headers.includes(els.nameColumn.value))return els.nameColumn.value;if(['email','recipient','to'].includes(lower)&&state.headers.includes(els.toColumn.value))return els.toColumn.value;const exact=state.headers.find(header=>header.toLocaleLowerCase()===lower);if(exact)return exact;const normalized=normalizedColumnKey(key);return state.headers.find(header=>normalizedColumnKey(header)===normalized)||'';}
function syncPlaceholderMappings({forceGuess=false}={}){
  const info=templatePlaceholderInfo(),keys=new Set(info.map(item=>item.key));const next={};
  if(forceGuess)state.placeholderMappingLocked=new Set();
  info.forEach(({key})=>{if(['_row','_today'].includes(key))return;const current=state.placeholderMappings[key];const locked=state.placeholderMappingLocked.has(key);if(!forceGuess&&locked)next[key]=current&&state.headers.includes(current)?current:'';else next[key]=!forceGuess&&current&&state.headers.includes(current)?current:guessPlaceholderColumn(key);});
  state.placeholderMappings=next;state.placeholderMappingLocked=new Set([...state.placeholderMappingLocked].filter(key=>keys.has(key)));renderPlaceholderMappings(info);
}
function currentSourceRow(){const renderedRow=state.rendered?.messages?.[state.messageIndex]?.row_number;const wanted=String(state.liveSheetRow||renderedRow||state.previewRows[0]?._row||'');return state.previewRows.find(row=>String(row._row)===wanted)||state.previewRows[0]||null;}
function sourceCell(row,column){if(!row||!column)return'';const override=state.rowOverrides[row._row]?.[column];return override!==undefined?override:(row[column]??'');}
function placeholderKeyFromSource(value){const parts=String(value||'').trim().split(/[^\p{L}\p{N}_]+/u).filter(Boolean);const joined=parts.map((part,index)=>index?part.charAt(0).toLocaleUpperCase()+part.slice(1):part).join('');return joined.replace(/^(\p{N})/u,'_$1').slice(0,80)||'Value';}
function validPlaceholderKey(value){const key=String(value||'').trim();return Boolean(key)&&key.length<=80&&!/[{}|\r\n]/.test(key)&&!key.startsWith('#')&&!key.startsWith('/');}
function validPlaceholderFallback(value){return !/[{}\r\n]/.test(String(value||''));}
function placeholderTargetLabel(){const target=state.activeEditor||els.bodyTemplate;return ({subjectTemplate:'Subject',bodyTemplate:'Plain message',bodyHtmlEditor:'Rich HTML',signatureHtmlEditor:'HTML signature',ccTemplate:'Cc',bccTemplate:'Bcc'})[target?.id]||'Message';}
function updatePlaceholderInsertTarget(){if(els.placeholderInsertTarget)els.placeholderInsertTarget.textContent=`Insert into · ${placeholderTargetLabel()}`;}
function renderPlaceholderSourceOptions(){
  const select=els.placeholderSourceSelect,previous=select.value;select.innerHTML='';const choose=document.createElement('option');choose.value='';choose.textContent='Choose a source…';select.append(choose);
  if(state.headers.length){const group=document.createElement('optgroup');group.label='Sheet columns';state.headers.forEach(header=>{const option=document.createElement('option');option.value=header;option.textContent=header;group.append(option);});select.append(group);}
  const other=document.createElement('optgroup');other.label='Other';[['__fallback__','No column · use fallback only'],['_row','Built in · Sheet row'],['_today','Built in · Today']].forEach(([value,label])=>{const option=document.createElement('option');option.value=value;option.textContent=label;other.append(option);});select.append(other);
  if([...select.options].some(option=>option.value===previous))select.value=previous;select.dataset.previous=select.value;
}
function choosePlaceholderSource(source){
  const previous=els.placeholderSourceSelect.dataset.previous||'';const currentName=els.placeholderNameInput.value.trim();els.placeholderSourceSelect.value=source;
  if(['_row','_today'].includes(source))els.placeholderNameInput.value=source;
  else if(source&&source!=='__fallback__'&&(!currentName||['_row','_today'].includes(currentName)||currentName===placeholderKeyFromSource(previous)))els.placeholderNameInput.value=placeholderKeyFromSource(source);
  else if(!source&&['_row','_today'].includes(currentName))els.placeholderNameInput.value='';
  els.placeholderSourceSelect.dataset.previous=source;updatePlaceholderBuilder();
}
function placeholderBuilderSpec(){
  const source=els.placeholderSourceSelect.value;let key=els.placeholderNameInput.value.trim();if(['_row','_today'].includes(source))key=source;const fallback=els.placeholderFallbackInput.value.trim();const keyValid=validPlaceholderKey(key),fallbackValid=validPlaceholderFallback(fallback);const token=key?`{{${key}${fallback&&!['_row','_today'].includes(source)?`|${fallback}`:''}}}`:'{{Placeholder}}';return{source,key,fallback,keyValid,fallbackValid,token};
}
function updatePlaceholderBuilder(){
  const spec=placeholderBuilderSpec(),sample=currentSourceRow(),builtin=['_row','_today'].includes(spec.source);els.placeholderNameInput.disabled=builtin;els.placeholderFallbackInput.disabled=builtin;els.placeholderTokenPreview.textContent=spec.token;updatePlaceholderInsertTarget();
  let sampleText='Choose a source';if(spec.source==='_row')sampleText=sample?String(sample._row):'Sheet row';else if(spec.source==='_today')sampleText=new Date().toISOString().slice(0,10);else if(spec.source==='__fallback__')sampleText=spec.fallback||'Add a fallback value';else if(spec.source){const value=sourceCell(sample,spec.source);sampleText=value||spec.fallback||'Blank in sample row';}
  els.placeholderSamplePreview.textContent=sampleText;const canInsert=spec.keyValid&&spec.fallbackValid&&Boolean(spec.source)&&(spec.source!=='__fallback__'||Boolean(spec.fallback));els.insertPlaceholderButton.disabled=!canInsert;els.insertConditionalButton.disabled=!canInsert||spec.source==='__fallback__';qsa('.placeholder-source-pill').forEach(button=>button.classList.toggle('is-selected',button.dataset.source===spec.source));
}
function applyPlaceholderBuilderMapping(spec){
  if(state.headers.includes(spec.source)){state.placeholderMappings[spec.key]=spec.source;state.placeholderMappingLocked.add(spec.key);}else if(spec.source==='__fallback__'){state.placeholderMappings[spec.key]='';state.placeholderMappingLocked.add(spec.key);}else{delete state.placeholderMappings[spec.key];state.placeholderMappingLocked.delete(spec.key);}
}
function insertPlaceholderFromBuilder(){
  const spec=placeholderBuilderSpec();if(!spec.keyValid){toast('Use a valid placeholder name','Names cannot contain braces, |, line breaks, or start with # or /.','error');return;}if(!spec.fallbackValid){toast('Fallback contains unsupported characters','Fallback values cannot contain braces or line breaks.','error');return;}if(!spec.source){toast('Choose what fills this placeholder','Pick a sheet column, built-in value, or fallback-only source.','error');return;}if(spec.source==='__fallback__'&&!spec.fallback){toast('Add a fallback value','Fallback-only placeholders need a value to insert.','error');return;}applyPlaceholderBuilderMapping(spec);insertIntoActive(spec.token);renderPlaceholderMappings();toast('Placeholder inserted',`${spec.token} → ${spec.source==='__fallback__'?'fallback':spec.source}`,'success',2600);
}
function insertConditionalFromBuilder(){const spec=placeholderBuilderSpec();if(!spec.keyValid||!spec.source||spec.source==='__fallback__'||!spec.fallbackValid)return;applyPlaceholderBuilderMapping(spec);insertIntoActive(`{{#if ${spec.key}}}${spec.token}{{/if}}`);renderPlaceholderMappings();toast('Conditional inserted',`Content will render only when ${spec.key} has a value.`,'success',2600);}
function replacePlaceholderTokensInText(text,key,fallback){const escaped=String(key).replace(/[.*+?^${}()|[\]\\]/g,'\\$&');const pattern=new RegExp(`{{\\s*${escaped}\\s*(?:\\|[^{}]*?)?\\s*}}`,'g');return String(text||'').replace(pattern,`{{${key}${fallback?`|${fallback}`:''}}}`);}
function setPlaceholderFallback(key,fallback){
  const value=String(fallback||'').trim();if(!validPlaceholderFallback(value)){toast('Fallback contains unsupported characters','Fallback values cannot contain braces or line breaks.','error');renderPlaceholderMappings();return;}[els.subjectTemplate,els.bodyTemplate,els.ccTemplate,els.bccTemplate].forEach(field=>{field.value=replacePlaceholderTokensInText(field.value,key,value);});[els.bodyHtmlEditor,els.signatureHtmlEditor].forEach(editor=>{const walker=document.createTreeWalker(editor,NodeFilter.SHOW_TEXT);const nodes=[];while(walker.nextNode())nodes.push(walker.currentNode);nodes.forEach(node=>{node.textContent=replacePlaceholderTokensInText(node.textContent,key,value);});});scheduleRender();
}
function renderPlaceholderMappings(info=templatePlaceholderInfo()){
  els.placeholderMappingList.innerHTML='';if(!info.length){els.placeholderMappingSummary.textContent='No placeholders in this template yet.';els.placeholderMappingList.innerHTML='<div class="empty-inline placeholder-empty-state">Create a placeholder above, or type one directly into the message.</div>';return;}
  const sample=currentSourceRow();let mappedCount=0,fallbackCount=0,needsCount=0;
  info.forEach(item=>{
    const builtin=['_row','_today'].includes(item.key),mapping=state.placeholderMappings[item.key]||'',mapped=state.headers.includes(mapping),usesFallback=!mapped&&Boolean(item.fallback),needs=!builtin&&((item.conditional&&!mapped)||(!item.conditional&&!mapped&&!item.fallback));if(mapped)mappedCount+=1;else if(usesFallback)fallbackCount+=1;if(needs)needsCount+=1;
    const row=document.createElement('div');row.className=`placeholder-map-row ${needs?'needs-attention':''}`;
    const identity=document.createElement('div');identity.className='placeholder-map-identity';const title=document.createElement('div');title.className='placeholder-map-token';const code=document.createElement('code');code.textContent=`{{${item.key}${item.fallback?`|${item.fallback}`:''}}}`;const status=document.createElement('span');status.className=`placeholder-map-status ${builtin?'built-in':needs?'attention':mapped?'mapped':'fallback'}`;status.textContent=builtin?'Built in':needs?'Needs mapping':mapped?'Mapped':'Fallback';title.append(code,status);identity.append(title);const meta=document.createElement('small');meta.textContent=item.conditional?(item.plain?'Used as value + condition':'Used as condition'):'Used as value';identity.append(meta);row.append(identity);
    if(builtin){const source=document.createElement('div');source.className='placeholder-map-built-in';source.innerHTML=`<span>Fill from</span><strong>${item.key==='_row'?'Sheet row':'Today'}</strong>`;row.append(source);const fallback=document.createElement('div');fallback.className='placeholder-map-built-in muted';fallback.innerHTML='<span>Fallback</span><strong>Not needed</strong>';row.append(fallback);const result=document.createElement('div');result.className='placeholder-map-result';const label=document.createElement('span');label.textContent='Sample';const strong=document.createElement('strong');strong.textContent=item.key==='_row'?(sample?String(sample._row):'Sheet row'):new Date().toISOString().slice(0,10);const insert=document.createElement('button');insert.type='button';insert.className='button ghost small';insert.textContent='Insert again';insert.addEventListener('click',()=>insertIntoActive(`{{${item.key}}}`));result.append(label,strong,insert);row.append(result);els.placeholderMappingList.append(row);return;}
    const sourceField=document.createElement('label');sourceField.className='placeholder-map-field';const sourceLabel=document.createElement('span');sourceLabel.textContent='Fill from';const select=document.createElement('select');select.className='placeholder-map-select';const none=document.createElement('option');none.value='';none.textContent=item.fallback?'No column · use fallback':'Not mapped';select.append(none);state.headers.forEach(header=>{const option=document.createElement('option');option.value=header;option.textContent=header;select.append(option);});select.value=mapping;select.addEventListener('change',()=>{state.placeholderMappings[item.key]=select.value;state.placeholderMappingLocked.add(item.key);renderPlaceholderMappings();scheduleRender({syncMappings:false});});sourceField.append(sourceLabel,select);row.append(sourceField);
    const fallbackField=document.createElement('label');fallbackField.className='placeholder-map-field';const fallbackLabel=document.createElement('span');fallbackLabel.textContent='Fallback if blank';const fallbackInput=document.createElement('input');fallbackInput.type='text';fallbackInput.maxLength=240;fallbackInput.value=item.fallback||'';fallbackInput.placeholder=item.plain?'Optional default':'Not used by condition';fallbackInput.disabled=!item.plain;fallbackInput.addEventListener('change',()=>setPlaceholderFallback(item.key,fallbackInput.value));fallbackField.append(fallbackLabel,fallbackInput);row.append(fallbackField);
    const result=document.createElement('div');result.className='placeholder-map-result';const resultLabel=document.createElement('span');resultLabel.textContent='Sample';const resultValue=document.createElement('strong');const value=sourceCell(sample,mapping);resultValue.textContent=mapped?(value||item.fallback||'Blank in sample row'):(item.fallback||'Choose a source');const insert=document.createElement('button');insert.type='button';insert.className='button ghost small';insert.textContent='Insert again';insert.addEventListener('click',()=>insertIntoActive(`{{${item.key}${item.fallback?`|${item.fallback}`:''}}}`));result.append(resultLabel,resultValue,insert);row.append(result);els.placeholderMappingList.append(row);
  });
  const parts=[`${info.length} placeholder${info.length===1?'':'s'}`];if(mappedCount)parts.push(`${mappedCount} mapped`);if(fallbackCount)parts.push(`${fallbackCount} using fallback`);if(needsCount)parts.push(`${needsCount} need attention`);els.placeholderMappingSummary.textContent=parts.join(' · ');els.placeholderMappingSummary.classList.toggle('has-warning',needsCount>0);
}
function autoMapPlaceholders(){syncPlaceholderMappings({forceGuess:true});scheduleRender({syncMappings:false});toast('Placeholders auto-matched','MailDesk matched reusable names to the closest sheet columns.','success',2600);}
function renderPlaceholders(){
  renderPlaceholderSourceOptions();els.placeholderList.innerHTML='';if(!state.headers.length){els.placeholderList.innerHTML='<span class="empty-inline">No sheet columns available yet.</span>';updatePlaceholderBuilder();return;}const quick=[...state.headers.slice(0,12),'_row','_today'];quick.forEach(source=>{const b=document.createElement('button');b.type='button';b.className='placeholder-pill placeholder-source-pill';b.dataset.source=source;b.textContent=source==='_row'?'Sheet row':source==='_today'?'Today':source;b.title=source.startsWith('_')?'Built-in value':`Fill from the “${source}” sheet column`;b.addEventListener('click',()=>choosePlaceholderSource(source));els.placeholderList.append(b);});if(state.headers.length>12){const more=document.createElement('span');more.className='placeholder-more';more.textContent=`+${state.headers.length-12} more in Fill from`;els.placeholderList.append(more);}updatePlaceholderBuilder();
}
function insertIntoActive(text){'''

regex_once(
    "mailmerge_app/static/app.js",
    r'''function templatePlaceholderInfo\(\)\{.*?function insertIntoActive\(text\)\{''',
    js_replacement,
)

replace_once(
    "mailmerge_app/static/app.js",
    "  els.templateSelect.addEventListener('change',loadTemplateIntoForm);els.autoMapPlaceholdersButton.addEventListener('click',autoMapPlaceholders);els.newTemplateButton.addEventListener('click',newTemplate);",
    "  els.templateSelect.addEventListener('change',loadTemplateIntoForm);els.autoMapPlaceholdersButton.addEventListener('click',autoMapPlaceholders);els.placeholderNameInput.addEventListener('input',updatePlaceholderBuilder);els.placeholderSourceSelect.addEventListener('change',()=>choosePlaceholderSource(els.placeholderSourceSelect.value));els.placeholderFallbackInput.addEventListener('input',updatePlaceholderBuilder);els.insertPlaceholderButton.addEventListener('click',insertPlaceholderFromBuilder);els.insertConditionalButton.addEventListener('click',insertConditionalFromBuilder);els.newTemplateButton.addEventListener('click',newTemplate);",
)
replace_once(
    "mailmerge_app/static/app.js",
    "[els.subjectTemplate,els.bodyTemplate,els.ccTemplate,els.bccTemplate].forEach(x=>{x.addEventListener('focus',()=>state.activeEditor=x);x.addEventListener('input',scheduleRender);});[els.bodyHtmlEditor,els.signatureHtmlEditor].forEach(x=>{x.addEventListener('focus',()=>state.activeEditor=x);x.addEventListener('input',scheduleRender);});",
    "[els.subjectTemplate,els.bodyTemplate,els.ccTemplate,els.bccTemplate].forEach(x=>{x.addEventListener('focus',()=>{state.activeEditor=x;updatePlaceholderInsertTarget();});x.addEventListener('input',scheduleRender);});[els.bodyHtmlEditor,els.signatureHtmlEditor].forEach(x=>{x.addEventListener('focus',()=>{state.activeEditor=x;updatePlaceholderInsertTarget();});x.addEventListener('input',scheduleRender);});",
)
replace_once(
    "mailmerge_app/static/app.js",
    "  {view:'campaign',step:2,selector:'.placeholder-mapper',title:'Personalize the message',text:'Templates stay reusable because placeholders map to this sheet’s columns. Auto-match gets you started, and defaults such as {{Name|there}} handle blanks.'},",
    "  {view:'campaign',step:2,selector:'.personalization-workbench',title:'Build personalization visually',text:'Create a reusable placeholder name, choose the sheet column that fills it, add an optional fallback, and preview a real row before inserting it. Used placeholders stay editable in the mapping table below.'},",
)

css = Path("mailmerge_app/static/app.css")
css.write_text(
    css.read_text(encoding="utf-8")
    + r'''

/* Guided personalization builder */
.personalization-workbench{margin-top:16px;display:grid;gap:12px}.personalization-builder{border:1px solid #cfdaf3;border-radius:14px;background:linear-gradient(180deg,#f8faff 0,#fff 68%);overflow:hidden;box-shadow:0 7px 22px rgba(35,88,215,.045)}.personalization-builder-head{display:flex;align-items:flex-start;justify-content:space-between;gap:16px;padding:14px 15px;border-bottom:1px solid #dfe6f4}.personalization-builder-head>div{display:grid;gap:2px}.personalization-builder-head strong{font-size:13px;letter-spacing:-.01em}.personalization-builder-head>div>span:last-child{font-size:10.8px;color:var(--muted);line-height:1.45}.section-kicker{font-size:9.5px!important;font-weight:760!important;text-transform:uppercase;letter-spacing:.08em;color:var(--accent)!important}.insert-target{white-space:nowrap;border:1px solid #c8d5f6;background:#eef3ff;color:#3457a7;border-radius:999px;padding:5px 8px;font-size:9.8px;font-weight:700}.placeholder-builder-grid{display:grid;grid-template-columns:minmax(130px,.75fr) minmax(190px,1.25fr) minmax(150px,1fr);gap:10px;padding:14px 15px 10px}.placeholder-builder-field>span{display:flex;align-items:center;gap:6px}.builder-step{width:17px;height:17px;border-radius:50%;display:inline-grid;place-items:center;background:#e8efff;color:#3159b5;font-size:9px}.placeholder-builder-preview{margin:0 15px 13px;border:1px solid var(--line);border-radius:11px;background:#fff;display:grid;grid-template-columns:minmax(150px,.8fr) minmax(150px,1fr) auto;align-items:stretch;overflow:hidden}.builder-preview-cell{min-width:0;padding:9px 11px;display:grid;gap:4px;border-right:1px solid var(--line)}.builder-preview-cell>span{font-size:9.5px;color:var(--faint);font-weight:700;text-transform:uppercase;letter-spacing:.05em}.builder-preview-cell code{width:max-content;max-width:100%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:#264796;background:#eef3ff}.builder-preview-cell strong{font-size:11.5px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.placeholder-builder-actions{display:flex;align-items:center;gap:6px;padding:8px;background:#fafbfd}.placeholder-quick-source{border-top:1px solid #e5eaf2;padding:10px 15px 13px;background:#fbfcff}.placeholder-quick-source>div:first-child{display:flex;align-items:baseline;gap:7px;margin-bottom:7px}.placeholder-quick-source>div:first-child>span{font-size:10.5px;font-weight:720;color:#4b5867}.placeholder-quick-source small{font-size:9.8px;color:var(--faint)}.placeholder-source-pill.is-selected{border-color:#86a2eb;background:#eef3ff;color:#244caa;box-shadow:0 0 0 2px #2358d70a}.placeholder-more{align-self:center;font-size:10px;color:var(--faint);padding:4px 2px}.placeholder-mapper{margin-top:0;background:#fff}.placeholder-mapper-head{padding:12px 13px}.placeholder-mapper-head span.has-warning{color:var(--warn);font-weight:650}.placeholder-empty-state{padding:15px}.placeholder-map-row{grid-template-columns:minmax(145px,.9fr) minmax(155px,1fr) minmax(145px,.9fr) minmax(150px,1fr);gap:10px;padding:10px 12px;align-items:end}.placeholder-map-row.needs-attention{background:#fffdf8}.placeholder-map-identity{align-self:center;min-width:0;display:grid;gap:4px}.placeholder-map-token{min-width:0;display:flex;align-items:center;gap:6px}.placeholder-map-token code{max-width:100%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.placeholder-map-identity small{font-size:9.5px;color:var(--faint)}.placeholder-map-status{flex:0 0 auto;border-radius:999px;padding:3px 5px;font-size:8px!important;font-weight:760;text-transform:uppercase;letter-spacing:.04em}.placeholder-map-status.mapped{background:var(--good-bg);color:var(--good)}.placeholder-map-status.fallback{background:#eef2f6;color:#5e6a77}.placeholder-map-status.attention{background:var(--warn-bg);color:var(--warn)}.placeholder-map-status.built-in{background:#edf2ff;color:#3159b5}.placeholder-map-field{display:grid;gap:4px;min-width:0}.placeholder-map-field>span,.placeholder-map-built-in>span,.placeholder-map-result>span{font-size:9.5px;color:var(--faint);font-weight:700;text-transform:uppercase;letter-spacing:.045em}.placeholder-map-field input,.placeholder-map-field select{width:100%;min-width:0;border:1px solid var(--line-strong);border-radius:8px;background:#fff;padding:7px 8px;font-size:10.8px;color:var(--text);outline:none}.placeholder-map-field input:focus,.placeholder-map-field select:focus{border-color:#7297f0;box-shadow:0 0 0 3px #2358d710}.placeholder-map-field input:disabled{background:#f3f5f7;color:#9099a3}.placeholder-map-built-in{align-self:stretch;display:grid;align-content:center;gap:4px;padding:7px 8px;border:1px solid var(--line);border-radius:8px;background:#f8fafb}.placeholder-map-built-in strong{font-size:10.8px}.placeholder-map-built-in.muted strong{color:var(--muted);font-weight:600}.placeholder-map-result{min-width:0;display:grid;grid-template-columns:1fr auto;grid-template-areas:'label action' 'value action';gap:2px 6px;align-items:center}.placeholder-map-result>span{grid-area:label}.placeholder-map-result>strong{grid-area:value;min-width:0;font-size:10.8px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.placeholder-map-result>button{grid-area:action}.placeholder-map-select{font-size:10.8px}.placeholder-map-sample{white-space:normal}
@media(max-width:980px){.placeholder-builder-grid{grid-template-columns:1fr 1fr}.placeholder-builder-field:last-child{grid-column:1/-1}.placeholder-builder-preview{grid-template-columns:1fr 1fr}.placeholder-builder-actions{grid-column:1/-1;border-top:1px solid var(--line);justify-content:flex-end}.placeholder-map-row{grid-template-columns:1fr 1fr}.placeholder-map-result{min-height:38px}}
@media(max-width:640px){.personalization-builder-head{display:grid}.insert-target{justify-self:start}.placeholder-builder-grid,.placeholder-builder-preview,.placeholder-map-row{grid-template-columns:1fr}.placeholder-builder-field:last-child{grid-column:auto}.builder-preview-cell{border-right:0;border-bottom:1px solid var(--line)}.placeholder-builder-actions{grid-column:auto;justify-content:stretch}.placeholder-builder-actions .button{flex:1}.placeholder-quick-source>div:first-child{display:grid}.placeholder-map-result{grid-template-columns:1fr auto}}
''',
    encoding="utf-8",
)

tests = Path("tests/test_frontend_integrity.py")
text = tests.read_text(encoding="utf-8")
marker = '''    def test_placeholder_mapping_ui_is_wired_to_render_payload(self):\n'''
addition = '''    def test_guided_placeholder_builder_covers_source_fallback_and_insertion(self):\n        for token in ('placeholderNameInput', 'placeholderSourceSelect', 'placeholderFallbackInput', 'placeholderTokenPreview', 'placeholderSamplePreview', 'placeholderInsertTarget', 'insertPlaceholderButton', 'insertConditionalButton', 'placeholderMappingSummary'):\n            self.assertIn(f'id="{token}"', INDEX_HTML)\n        self.assertIn('function insertPlaceholderFromBuilder()', APP_JS)\n        self.assertIn('function insertConditionalFromBuilder()', APP_JS)\n        self.assertIn('function setPlaceholderFallback(key,fallback)', APP_JS)\n        self.assertIn('placeholderMappingLocked', APP_JS)\n        self.assertIn("No column · use fallback only", APP_JS)\n        self.assertIn("selector:'.personalization-workbench'", APP_JS)\n\n'''
if marker not in text:
    raise SystemExit("frontend placeholder test marker missing")
tests.write_text(text.replace(marker, addition + marker, 1), encoding="utf-8")
