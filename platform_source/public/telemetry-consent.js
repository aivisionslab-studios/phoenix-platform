(() => {
  const API = '/api/forge/telemetry';
  const $ = (id) => document.getElementById(id);
  let state = null;
  let notice = null;
  const POS_KEY='phoenix.telemetryPill.position.v1';
  let drag=null;
  let suppressClickUntil=0;

  const css = `
#phx-telemetry-pill{position:fixed;right:18px;top:108px;z-index:2147483000;border:1px solid #303842;background:#11161c;color:#dbe4ee;border-radius:999px;padding:8px 12px;font:600 11px/1.2 'JetBrains Mono',monospace;box-shadow:0 10px 32px #0008;cursor:grab;display:flex;gap:8px;align-items:center;touch-action:none;user-select:none;-webkit-user-select:none}#phx-telemetry-pill.phx-dragging{cursor:grabbing;box-shadow:0 14px 42px #000b,0 0 0 1px #4aa3ff66}
#phx-telemetry-pill .dot{width:8px;height:8px;border-radius:50%;background:#7a8592}.phx-t-on .dot{background:#37d67a;box-shadow:0 0 8px #37d67a88}.phx-t-off .dot{background:#ff334b}
#phx-telemetry-modal{position:fixed;inset:0;z-index:2147483640;background:#000b;display:flex;align-items:center;justify-content:center;padding:24px;font-family:'JetBrains Mono',monospace;color:#e7edf4}
#phx-telemetry-card{width:min(760px,96vw);max-height:88vh;overflow:auto;background:#0d1117;border:1px solid #323b46;border-radius:14px;box-shadow:0 25px 80px #000;padding:0}
#phx-telemetry-card header{padding:18px 20px;border-bottom:1px solid #252d36;display:flex;justify-content:space-between;gap:16px;align-items:start}
#phx-telemetry-card h2{margin:0;color:#fff;font-size:16px;letter-spacing:.08em}#phx-telemetry-card p{color:#a9b5c2;font-size:12px;line-height:1.65}
#phx-telemetry-body{padding:18px 20px}.phx-t-grid{display:grid;grid-template-columns:1fr 1fr;gap:12px}.phx-t-box{background:#121820;border:1px solid #29313a;border-radius:10px;padding:12px}.phx-t-box strong{font-size:11px;color:#fff}.phx-t-box ul{padding-left:18px;color:#9faebe;font-size:11px;line-height:1.6}
.phx-t-cat{display:flex;gap:8px;align-items:center;font-size:11px;color:#c8d2dc;margin:7px 0}.phx-t-actions{display:flex;gap:9px;justify-content:flex-end;flex-wrap:wrap;padding-top:16px;border-top:1px solid #252d36;margin-top:16px}.phx-t-btn{border:1px solid #39434e;background:#151c24;color:#e7edf4;border-radius:7px;padding:9px 13px;font:700 11px 'JetBrains Mono',monospace;cursor:pointer}.phx-t-btn:hover{filter:brightness(1.15)}.phx-t-primary{background:#ff334b;border-color:#ff334b;color:#fff}.phx-t-danger{border-color:#ff334b66;color:#ff7182}.phx-t-good{background:#143b2b;border-color:#2b8f61;color:#baffd9}
#phx-telemetry-preview{white-space:pre-wrap;word-break:break-word;background:#080b0f;border:1px solid #28313b;padding:12px;border-radius:8px;font-size:10px;color:#a8d3ff;max-height:300px;overflow:auto;display:none}.phx-t-note{background:#14202a;border-left:3px solid #4aa3ff;padding:10px 12px;font-size:11px;color:#c8d8e8}.phx-t-local{color:#77c7ff}.phx-t-shared{color:#ffbd66}@media(max-width:900px){#phx-telemetry-pill{padding:7px 10px;font-size:10px}}@media(max-width:700px){.phx-t-grid{grid-template-columns:1fr}}
`;

  function injectStyle(){ if(document.getElementById('phx-telemetry-style')) return; const s=document.createElement('style');s.id='phx-telemetry-style';s.textContent=css;document.head.appendChild(s); }
  async function jfetch(url, opts={}){ const r=await fetch(url,{cache:'no-store',...opts,headers:{'Content-Type':'application/json',...(opts.headers||{})}}); const b=await r.json().catch(()=>({})); if(!r.ok) throw new Error(b.detail||b.error||`HTTP ${r.status}`); return b; }
  function esc(x){return String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
  function consentState(){ const c=state?.consent||{}; return {on:Boolean(c.consent), required:Boolean(c.notice_required), version:c.notice_version||notice?.notice_version||''}; }
  function clampPill(x,y,p){
    const pad=8,w=p.offsetWidth||150,h=p.offsetHeight||34;
    return {x:Math.max(pad,Math.min(x,window.innerWidth-w-pad)),y:Math.max(pad,Math.min(y,window.innerHeight-h-pad))};
  }
  function savePillPosition(p){try{localStorage.setItem(POS_KEY,JSON.stringify({left:parseFloat(p.style.left)||p.getBoundingClientRect().left,top:parseFloat(p.style.top)||p.getBoundingClientRect().top}));}catch(_){}}
  function restorePillPosition(p){
    let pos=null;try{pos=JSON.parse(localStorage.getItem(POS_KEY)||'null');}catch(_){}
    if(pos&&Number.isFinite(pos.left)&&Number.isFinite(pos.top)){const c=clampPill(pos.left,pos.top,p);p.style.left=`${c.x}px`;p.style.top=`${c.y}px`;p.style.right='auto';p.style.bottom='auto';}
  }
  function resetPillPosition(p){try{localStorage.removeItem(POS_KEY);}catch(_){}p.style.left='auto';p.style.bottom='auto';p.style.right='18px';p.style.top='108px';}
  function wirePillDrag(p){
    if(p.dataset.phxDragWired==='1') return;p.dataset.phxDragWired='1';
    p.title='Clique para abrir. Arraste para mover. Duplo clique restaura a posição.';
    p.addEventListener('pointerdown',(e)=>{if(e.button!==0)return;const r=p.getBoundingClientRect();drag={id:e.pointerId,startX:e.clientX,startY:e.clientY,offsetX:e.clientX-r.left,offsetY:e.clientY-r.top,moved:false};p.setPointerCapture?.(e.pointerId);p.classList.add('phx-dragging');});
    p.addEventListener('pointermove',(e)=>{if(!drag||drag.id!==e.pointerId)return;const dx=e.clientX-drag.startX,dy=e.clientY-drag.startY;if(Math.hypot(dx,dy)>4)drag.moved=true;if(!drag.moved)return;const c=clampPill(e.clientX-drag.offsetX,e.clientY-drag.offsetY,p);p.style.left=`${c.x}px`;p.style.top=`${c.y}px`;p.style.right='auto';p.style.bottom='auto';e.preventDefault();});
    const end=(e)=>{if(!drag||drag.id!==e.pointerId)return;const moved=drag.moved;drag=null;p.classList.remove('phx-dragging');try{p.releasePointerCapture?.(e.pointerId);}catch(_){}if(moved){savePillPosition(p);suppressClickUntil=Date.now()+350;e.preventDefault();}};
    p.addEventListener('pointerup',end);p.addEventListener('pointercancel',end);
    p.addEventListener('dblclick',(e)=>{e.preventDefault();suppressClickUntil=Date.now()+350;resetPillPosition(p);});
    window.addEventListener('resize',()=>{const r=p.getBoundingClientRect(),c=clampPill(r.left,r.top,p);p.style.left=`${c.x}px`;p.style.top=`${c.y}px`;p.style.right='auto';p.style.bottom='auto';savePillPosition(p);});
  }
  function renderPill(){
    let p=$('phx-telemetry-pill');
    if(!p){p=document.createElement('button');p.id='phx-telemetry-pill';p.addEventListener('click',(e)=>{if(Date.now()<suppressClickUntil){e.preventDefault();return;}openModal(false);});document.body.appendChild(p);wirePillDrag(p);requestAnimationFrame(()=>restorePillPosition(p));}
    const c=consentState();p.className=c.on?'phx-t-on':'phx-t-off';p.innerHTML=`<span class="dot"></span><span>TELEMETRIA: ${c.on?'ATIVA':'DESATIVADA'}</span>`;
  }
  function categoriesHtml(){ const cats=state?.consent?.categories||{}; return Object.entries(cats).map(([k,v])=>`<label class="phx-t-cat"><input type="checkbox" data-phx-cat="${esc(k)}" ${v?'checked':''}> ${esc(k)}</label>`).join(''); }
  async function showPreview(){ const pre=$('phx-telemetry-preview');pre.style.display='block';pre.textContent='Gerando preview sanitizado...'; try{const p=await jfetch(`${API}/preview`);if(p.status==='WARMING'||p.status==='REFRESHING'){pre.textContent='Preview em preparação. O Forge está atualizando o snapshot em segundo plano; tente novamente em alguns segundos.';return;}pre.textContent=JSON.stringify(p.payload??p,null,2);}catch(e){pre.textContent=`Preview temporariamente indisponível: ${e.message||e}`;} }
  async function accept(){ const cats={};document.querySelectorAll('[data-phx-cat]').forEach(x=>cats[x.getAttribute('data-phx-cat')]=x.checked); try{state=await jfetch(`${API}/consent`,{method:'POST',body:JSON.stringify({accepted_notice_version:notice.notice_version,categories:cats})}); await refresh(); closeModal();}catch(e){alert(`Não foi possível salvar o consentimento: ${e.message||e}`);} }
  async function decline(){ try{await jfetch(`${API}/revoke`,{method:'POST',body:'{}'});await refresh();closeModal();}catch(e){alert(`Não foi possível salvar sua escolha: ${e.message||e}`);} }
  async function sendNow(){ try{const x=await jfetch(`${API}/send`,{method:'POST',body:'{}'});alert(`Telemetria: ${x.status||'processada'}`);await refresh();}catch(e){alert(`Falha ao enviar: ${e.message||e}`);} }
  function closeModal(){ $('phx-telemetry-modal')?.remove(); }
  function openModal(auto){
    closeModal(); const c=consentState(); const may=(notice?.may_collect||[]).map(x=>`<li>${esc(x)}</li>`).join(''); const never=(notice?.never_collect_by_policy||[]).map(x=>`<li>${esc(x)}</li>`).join('');
    const m=document.createElement('div');m.id='phx-telemetry-modal';m.innerHTML=`<div id="phx-telemetry-card"><header><div><h2>PHOENIX // PRIVACIDADE E TELEMETRIA</h2><p>${esc(notice?.summary||'Telemetria técnica opcional do Phoenix Forge.')}</p></div>${auto?'':'<button class="phx-t-btn" id="phx-t-close">Fechar</button>'}</header><div id="phx-telemetry-body"><div class="phx-t-note"><b class="phx-t-local">Coleta local</b>: usada pelo Forge/AHDE para diagnosticar e operar a máquina; permanece local. <b class="phx-t-shared">Telemetria compartilhada</b>: opcional e só sai da máquina após seu consentimento.</div><div class="phx-t-grid" style="margin-top:12px"><div class="phx-t-box"><strong>PODE SER COMPARTILHADO</strong><ul>${may}</ul></div><div class="phx-t-box"><strong>NUNCA ENVIADO PELA POLÍTICA</strong><ul>${never}</ul></div></div><div class="phx-t-box" style="margin-top:12px"><strong>CATEGORIAS</strong>${categoriesHtml()}</div><div style="margin-top:12px"><button class="phx-t-btn" id="phx-t-preview-btn">Ver exatamente o payload sanitizado</button><pre id="phx-telemetry-preview"></pre></div><div class="phx-t-actions">${c.on?'<button class="phx-t-btn phx-t-danger" id="phx-t-decline">Desativar / revogar</button><button class="phx-t-btn" id="phx-t-send">Enviar agora</button>':'<button class="phx-t-btn" id="phx-t-decline">Não compartilhar</button><button class="phx-t-btn phx-t-primary" id="phx-t-accept">Aceitar telemetria</button>'}</div></div></div>`;
    document.body.appendChild(m);$('phx-t-close')?.addEventListener('click',closeModal);$('phx-t-preview-btn')?.addEventListener('click',showPreview);$('phx-t-accept')?.addEventListener('click',accept);$('phx-t-decline')?.addEventListener('click',decline);$('phx-t-send')?.addEventListener('click',sendNow);
  }
  async function refresh(){ try{notice=await jfetch(`${API}/privacy-notice`);state=await jfetch(`${API}/status`);renderPill();const c=consentState();if(c.required && !$('phx-telemetry-modal')) openModal(true);}catch(e){console.warn('[Phoenix Telemetry UI] indisponível:',e);} }
  injectStyle(); if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',()=>setTimeout(refresh,900));else setTimeout(refresh,900);
})();
