"""Generate a self-contained offline workspace for a governed annotation package."""

from __future__ import annotations

import html
import json
from pathlib import Path

from .annotation_sampling import validate_annotation_package


def build_annotation_workspace(sample_path: Path, package_path: Path) -> str:
    """Return an offline HTML reviewer that exports the unchanged package contract."""
    package = validate_annotation_package(sample_path, package_path)
    payload = json.dumps(package, sort_keys=True, separators=(",", ":"))
    payload = payload.replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e")
    title = html.escape(f"RegImpact annotation package {package['annotator_slot']}")
    return _TEMPLATE.replace("{{TITLE}}", title).replace("{{PACKAGE_JSON}}", payload)


_TEMPLATE = r'''<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:; connect-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'">
  <title>{{TITLE}}</title>
  <style>
    :root{color-scheme:light;--ink:#14213d;--muted:#5f6b7a;--line:#dbe3ee;--brand:#2357d8;--soft:#f5f7fb;--ok:#087f5b}
    *{box-sizing:border-box}body{margin:0;font:15px/1.5 Inter,system-ui,sans-serif;color:var(--ink);background:var(--soft)}
    header{position:sticky;top:0;z-index:2;background:#fff;border-bottom:1px solid var(--line);padding:14px 24px;display:flex;gap:18px;align-items:center;flex-wrap:wrap}
    h1{font-size:18px;margin:0}.meta{color:var(--muted)}.progress{margin-left:auto;min-width:220px}.bar{height:8px;background:#e7ecf4;border-radius:9px;overflow:hidden}.bar i{display:block;height:100%;background:var(--ok);width:0}
    main{max-width:1100px;margin:24px auto;padding:0 20px;display:grid;grid-template-columns:minmax(0,1fr) 300px;gap:20px}.card{background:#fff;border:1px solid var(--line);border-radius:12px;padding:22px;box-shadow:0 2px 9px #172b4d0d}
    .eyebrow{font-size:12px;letter-spacing:.08em;text-transform:uppercase;color:var(--muted)}h2{font-size:20px;margin:5px 0}.clause{font:18px/1.65 Georgia,serif;padding:18px;background:#f8faff;border-left:4px solid var(--brand);margin:18px 0;white-space:pre-wrap}
    .labels{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}.labels label{border:1px solid var(--line);border-radius:8px;padding:10px;cursor:pointer}.labels label:has(input:checked){border-color:var(--brand);background:#eef3ff}.labels input{margin-right:7px}
    input[type=text],textarea{width:100%;border:1px solid var(--line);border-radius:7px;padding:9px;font:inherit}textarea{min-height:90px;resize:vertical}.field{margin:14px 0}.field>label{font-weight:650;display:block;margin-bottom:5px}
    nav{display:flex;gap:9px;margin-top:18px;flex-wrap:wrap}button,.button{border:1px solid var(--line);background:#fff;color:var(--ink);padding:9px 13px;border-radius:7px;font-weight:650;cursor:pointer;text-decoration:none}button.primary{background:var(--brand);border-color:var(--brand);color:#fff}button:disabled{opacity:.45;cursor:not-allowed}
    .guide h3{margin:0 0 10px}.guide ol{padding-left:20px}.guide li{margin:7px 0}.warning{font-size:13px;color:#7a4d00;background:#fff7df;padding:10px;border-radius:7px}.status{font-size:13px;color:var(--ok);min-height:20px}.source{word-break:break-word}
    @media(max-width:800px){main{grid-template-columns:1fr}.progress{margin-left:0;width:100%}.labels{grid-template-columns:1fr}}
  </style>
</head>
<body>
<header>
  <h1>{{TITLE}}</h1><span class="meta" id="position"></span>
  <div class="progress"><div class="meta" id="progressText"></div><div class="bar"><i id="progressBar"></i></div></div>
</header>
<main>
  <section class="card">
    <div class="field"><label for="annotator">Your annotator ID</label><input id="annotator" type="text" autocomplete="off" placeholder="Enter your assigned ID"></div>
    <div class="eyebrow" id="regulator"></div><h2 id="heading"></h2>
    <div class="meta" id="lineage"></div><div class="clause" id="clause"></div>
    <a class="button source" id="source" target="_blank" rel="noopener noreferrer">Open official source</a>
    <div class="field"><label>Choose exactly one label</label><div class="labels" id="labels"></div></div>
    <div class="field"><label for="notes">Notes (optional)</label><textarea id="notes" placeholder="Record ambiguity or context for adjudication"></textarea></div>
    <div class="status" id="status" role="status"></div>
    <nav><button id="previous">Previous</button><button id="next" class="primary">Save &amp; next</button><button id="nextOpen">Next unlabeled</button></nav>
  </section>
  <aside class="card guide">
    <h3>Decision order</h3>
    <ol><li>Reporting requirement</li><li>Record-retention requirement</li><li>Prohibition</li><li>Permission</li><li>Definition</li><li>Other obligation</li><li>Non-obligation</li></ol>
    <p class="warning">Work independently. Do not view another annotator's labels. Sampling heuristics are not shown and are not ground truth.</p>
    <div class="field"><button id="export" class="primary">Export progress JSON</button></div>
    <div class="field"><label for="importFile">Resume from exported JSON</label><input id="importFile" type="file" accept="application/json,.json"></div>
    <button id="clear">Clear local saved progress</button>
  </aside>
</main>
<script id="packageData" type="application/json">{{PACKAGE_JSON}}</script>
<script>
'use strict';
const original=JSON.parse(document.getElementById('packageData').textContent);
let state=structuredClone(original),index=0;
const labels={reporting_requirement:'Reporting requirement',record_retention_requirement:'Record retention',prohibition:'Prohibition',permission:'Permission',definition:'Definition',obligation:'Other obligation',non_obligation:'Non-obligation'};
const key=`regimpact:${original.sample_sha256}:${original.package_id}`;
const immutable=['clause_id','document_id','regulator','source_url','section_id','heading','page','text','text_sha256','guideline_version'];
const $=id=>document.getElementById(id);
function awareTimestamp(value){
  if(typeof value!=='string')return false;
  const match=/^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,6}))?(Z|[+-]\d{2}:?\d{2})$/.exec(value);
  if(!match)return false;
  const [year,month,day,hour,minute,second]=match.slice(1,7).map(Number),offset=match[8];
  const probe=new Date(Date.UTC(year,month-1,day,hour,minute,second));
  const validCalendar=probe.getUTCFullYear()===year&&probe.getUTCMonth()===month-1&&probe.getUTCDate()===day&&probe.getUTCHours()===hour&&probe.getUTCMinutes()===minute&&probe.getUTCSeconds()===second;
  if(!validCalendar)return false;
  if(offset==='Z')return true;
  const parts=offset.slice(1).replace(':','');
  return Number(parts.slice(0,2))<24&&Number(parts.slice(2))<60;
}
function validImport(value){
  if(!value||typeof value!=='object'||value.schema_version!==original.schema_version||value.package_id!==original.package_id||value.annotator_slot!==original.annotator_slot||value.sample_sha256!==original.sample_sha256||value.candidate_queue_sha256!==original.candidate_queue_sha256||value.sampling_policy_version!==original.sampling_policy_version||value.guideline_version!==original.guideline_version||JSON.stringify(value.allowed_labels)!==JSON.stringify(original.allowed_labels)||value.labels_visible_from_other_annotator!==false||value.model_training_authorized!==false||!Array.isArray(value.tasks)||value.tasks.length!==original.tasks.length)return false;
  if(value.annotator_id!==null&&(typeof value.annotator_id!=='string'||!value.annotator_id.trim()))return false;
  const incoming=new Map(value.tasks.map(x=>[x.clause_id,x]));
  if(incoming.size!==value.tasks.length)return false;
  return original.tasks.every(task=>{const other=incoming.get(task.clause_id);if(!other||!immutable.every(field=>JSON.stringify(task[field])===JSON.stringify(other[field]))||typeof other.notes!=='string')return false;if(other.label===null)return other.annotated_at===null;return original.allowed_labels.includes(other.label)&&awareTimestamp(other.annotated_at);});
}
function save(){state.annotator_id=$('annotator').value.trim()||null;localStorage.setItem(key,JSON.stringify(state));updateProgress();}
function loadSaved(){try{const saved=JSON.parse(localStorage.getItem(key));if(validImport(saved))state=saved;}catch(_){localStorage.removeItem(key);}}
function updateProgress(){const done=state.tasks.filter(x=>x.label!==null).length;$('progressText').textContent=`${done} of ${state.tasks.length} labelled`;$('progressBar').style.width=`${100*done/state.tasks.length}%`;}
function render(){const task=state.tasks[index];$('position').textContent=`Clause ${index+1} of ${state.tasks.length}`;$('annotator').value=state.annotator_id||'';$('regulator').textContent=task.regulator;$('heading').textContent=task.heading;$('lineage').textContent=`${task.document_id} · ${task.section_id}${task.page===null?'':' · page '+task.page}`;$('clause').textContent=task.text;$('source').href=task.source_url;$('notes').value=task.notes||'';
  $('labels').innerHTML='';for(const value of original.allowed_labels){const label=document.createElement('label'),radio=document.createElement('input');radio.type='radio';radio.name='label';radio.value=value;radio.checked=task.label===value;radio.addEventListener('change',()=>{task.label=value;task.annotated_at=new Date().toISOString();save();$('status').textContent='Saved locally';});label.append(radio,document.createTextNode(labels[value]));$('labels').append(label);}
  $('previous').disabled=index===0;$('next').disabled=index===state.tasks.length-1;updateProgress();
}
function persistNotes(){state.tasks[index].notes=$('notes').value;save();}
$('annotator').addEventListener('change',save);$('notes').addEventListener('change',persistNotes);
$('previous').onclick=()=>{persistNotes();index--;render();};$('next').onclick=()=>{persistNotes();index++;render();};
$('nextOpen').onclick=()=>{persistNotes();const found=state.tasks.findIndex((x,i)=>i>index&&x.label===null);index=found>=0?found:(state.tasks.findIndex(x=>x.label===null));if(index<0)index=state.tasks.length-1;render();};
$('export').onclick=()=>{persistNotes();if(!state.annotator_id){$('status').textContent='Enter your annotator ID before export';return;}const blob=new Blob([JSON.stringify(state,null,2)+'\n'],{type:'application/json'}),a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download=`${state.package_id}-progress.json`;a.click();setTimeout(()=>URL.revokeObjectURL(a.href),0);$('status').textContent='Progress exported';};
$('importFile').onchange=async event=>{try{const value=JSON.parse(await event.target.files[0].text());if(!validImport(value))throw new Error('Package identity or immutable task data does not match');state=value;save();index=0;render();$('status').textContent='Progress imported and validated';}catch(error){$('status').textContent=`Import rejected: ${error.message}`;}};
$('clear').onclick=()=>{if(confirm('Clear only this package\'s local browser progress?')){localStorage.removeItem(key);state=structuredClone(original);index=0;render();}};
loadSaved();render();
</script>
</body></html>'''
