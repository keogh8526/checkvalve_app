const S={parts:[],stem:null,job:null,bundle:null,poll:null,llm:false,part_id:''};
let TOKEN=0;
const $=(s,r=document)=>r.querySelector(s);
function h(t,a={},...k){const e=document.createElement(t);
 for(const[n,v]of Object.entries(a)){if(n==='class')e.className=v;else if(n==='html')e.innerHTML=v;
  else if(n.startsWith('on'))e.addEventListener(n.slice(2),v);
  else if(v===false||v==null){}else e.setAttribute(n,v);}
 for(const c of k.flat())e.append(c&&c.nodeType?c:document.createTextNode(c==null?'':c));return e;}
const mmss=t=>{t=Math.max(0,t|0);return (t/60|0)+':'+String(t%60).padStart(2,'0');};
function toast(m,k='ok'){const t=$('#toast');t.textContent=m;t.className='toast '+k;t.hidden=false;
 clearTimeout(t._h);t._h=setTimeout(()=>t.hidden=true,3200);}
async function api(m,p,b){const o={method:m,headers:{}};
 if(b!==undefined){o.headers['Content-Type']='application/json';o.body=JSON.stringify(b);}
 const r=await fetch(p,o);const ct=r.headers.get('content-type')||'';
 const d=ct.includes('json')?await r.json():await r.text();
 if(!r.ok)throw Object.assign(new Error((d&&d.error)||('HTTP '+r.status)),{status:r.status,payload:d});return d;}
const API={parts:()=>api('GET','/api/parts'),
 run:(stem,use_llm)=>api('POST','/api/run',{stem,use_llm}),
 status:j=>api('GET','/api/status?job='+encodeURIComponent(j)),
 bundle:j=>api('GET','/api/bundle?job='+encodeURIComponent(j)),
 putStep:(job,no,fields)=>api('PUT','/api/step',{job,no,fields}),
 reviewStep:(job,no)=>api('POST','/api/step/review',{job,no}),
 approve:(job,signed_by)=>api('POST','/api/approve',{job,signed_by}),
 export_:job=>api('POST','/api/export',{job})};
const SCREENS=['ingest','run','preview','review','approve'];
const RENDER={ingest:renderIngest,run:renderRun,preview:renderPreview,review:renderReview,approve:renderApprove};
const go=n=>{location.hash='#/'+n;};
function setStep(n){const i=SCREENS.indexOf(n);
 [...$('#wizard').children].forEach((b,x)=>{b.classList.toggle('active',x===i);
  b.classList.toggle('done',x<i);b.classList.toggle('locked',x>=2&&!S.job);});
 const jp=$('#jobPill');if(S.job){jp.hidden=false;jp.textContent='작업 '+S.job.slice(-6);}else jp.hidden=true;}
async function route(){const my=++TOKEN;
 const n=(location.hash.slice(2)||'ingest').split('?')[0];
 const t=SCREENS.includes(n)?n:'ingest';
 if(t!=='ingest'&&t!=='run'&&!S.job){toast('먼저 클립을 생성하세요','warn');return go('run');}
 setStep(t);$('#app').replaceChildren();
 try{await RENDER[t](my);}catch(e){if(my===TOKEN)$('#app').append(h('div',{class:'err'},'화면 로드 실패: '+e.message));}}
document.addEventListener('DOMContentLoaded',()=>{
 $('#wizard').addEventListener('click',e=>{const b=e.target.closest('.wz');
  if(b&&!b.classList.contains('locked'))go(b.dataset.screen);});
 window.addEventListener('hashchange',route);init();});

async function init(){S.job=sessionStorage.getItem('job')||null;
 try{const p=await API.parts();S.parts=p.parts||[];S.llm=!!p.llm_available;S.part_id=p.part_id||'';
  $('#partTag').textContent=' · '+S.part_id;}catch(e){}
 if(S.job){try{const st=await API.status(S.job);
   if(st.state==='error'||st.state==='unknown'){sessionStorage.removeItem('job');S.job=null;}
   else S.stem=st.stem||S.stem;}catch(e){sessionStorage.removeItem('job');S.job=null;}}
 route();}

// ① 수집
async function renderIngest(my){const d=await API.parts();if(my!==TOKEN)return;S.parts=d.parts;S.llm=!!d.llm_available;
 const rows=d.parts.map(p=>h('tr',{},
  h('td',{},p.stem.slice(-9)),h('td',{},p.shot_type),
  h('td',{},(p.roles||[]).join(', ')+(p.is_timeline?' ★타임라인':'')),
  h('td',{html:p.has_guide?'<span class="chip grounded">생성됨</span>':'—'}),
  h('td',{},h('button',{class:'btn',onclick:()=>{S.stem=p.stem;go('run');}},'선택'))));
 $('#app').append(
  h('div',{class:'card'},h('h2',{},'① 클립 수집 / 역할'),
   h('table',{},h('thead',{},h('tr',{},...['클립','샷','역할','지도서',''].map(x=>h('th',{},x)))),
    h('tbody',{},...rows)),
   h('p',{class:'bar-warn'},'역할 수동 보정 · 사양 PDF 파싱은 이후 단계입니다 (자리표시자).')),
  h('div',{class:'card'},h('h3',{},'사양 PDF 업로드 (자리표시자)'),
   h('input',{type:'file',accept:'application/pdf',onchange:uploadDoc}),
   h('div',{id:'docNote',class:'mut'})));}
async function uploadDoc(e){const f=e.target.files[0];if(!f)return;
 try{const r=await fetch('/api/doc?part_id='+encodeURIComponent(S.part_id),
  {method:'POST',headers:{'Content-Type':'application/pdf'},body:await f.arrayBuffer()});
  const j=await r.json();$('#docNote').textContent='저장됨: '+f.name+' · '+(j.spec?.note||'');}
 catch(err){toast('업로드 실패','err');}}

// ② 실행
async function renderRun(my){const p=S.parts.find(x=>x.stem===S.stem)||S.parts[0];S.stem=p?.stem;
 const card=h('div',{class:'card'},h('h2',{},'② 생성 실행'),
  h('p',{},'대상 클립: ',h('b',{},S.stem?S.stem.slice(-9):'—'),p?.is_timeline?' (타임라인)':''));
 const llm=h('label',{class:S.llm?'':'hidden'},h('input',{type:'checkbox',id:'llmChk'}),' Claude 비전 사용');
 const btn=h('button',{class:'btn',onclick:start},'작업지도서 생성');
 const bar=h('div',{id:'runbar'});card.append(llm,btn,bar);$('#app').append(card);
 async function start(){btn.disabled=true;
  try{const use_llm=(S.llm&&$('#llmChk')?.checked)||false;
   const {job_id}=await API.run(S.stem,use_llm);S.job=job_id;sessionStorage.setItem('job',job_id);poll();}
  catch(e){btn.disabled=false;if(e.status===409){S.job=e.payload.job_id;sessionStorage.setItem('job',S.job);poll();}
   else toast(e.message,'err');}}
 function poll(){clearInterval(S.poll);
  S.poll=setInterval(async()=>{let st;try{st=await API.status(S.job);}catch(e){return;}
   bar.replaceChildren(h('div',{},'상태: ',h('b',{},st.state),' · ',st.stage||'',' ',st.pct+'%'),
    h('pre',{class:'logtail'},(st.log_tail||[]).slice(-8).join('\n')));
   if(st.state==='done'){clearInterval(S.poll);toast('생성 완료','ok');go('preview');}
   if(st.state==='error'){clearInterval(S.poll);
    bar.append(h('div',{class:'err'},'생성 실패: '+(st.error||'')),h('button',{class:'btn',onclick:start},'재시도'));}},900);}
 if(S.job)poll();}

// ③ 미리보기
async function renderPreview(my){const p=S.parts.find(x=>x.stem===S.stem);
 const wrap=h('div',{class:'card'},h('h2',{},'③ 미리보기 (실제 산출물)'));
 if(p&&!p.is_timeline)wrap.append(h('p',{class:'bar-warn'},'미리보기 영상은 타임라인 클립 전용입니다.'));
 const url=()=>'/api/preview?job='+encodeURIComponent(S.job)+'&t='+Date.now();
 const fr=h('iframe',{title:'deliverable'});fr.src=url();
 wrap.append(h('div',{class:'iframewrap'},fr),
  h('div',{class:'row'},h('button',{class:'btn ghost',onclick:()=>go('review')},'검수로'),
   h('button',{class:'btn ghost',onclick:()=>{fr.src=url();}},'새로고침')));
 $('#app').append(wrap);}

// ④ 검수·라벨편집
function countReviewed(b){return b.STEPS.filter(s=>s.reviewed).length;}
async function renderReview(my){const b=await API.bundle(S.job);if(my!==TOKEN)return;S.bundle=b;
 const r=b.review,need=new Set(r.needs_review||[]),blk=new Set(r.blocked||[]);
 const banner=h('div',{class:r.approved?'chip grounded':r.evidence_ok?'bar-warn':'err'},
  r.approved?'승인 완료':r.evidence_ok?('근거 충족 · 서명 대기 · 검수 '+countReviewed(b)+'/'+r.total_steps):
  ('미승인 · 검수 '+(r.needs_review||[]).length+'건'));
 const warn=(r.warnings||[]).length?h('ul',{class:'warns'},...r.warnings.map(w=>h('li',{},w))):'';
 const provChip=p=>({'rag:gold':'grounded','rag':'rag','manual':'grounded','human':'grounded','stub':'stub'}[p]||'rag');
 async function save(no,fields){try{await API.putStep(S.job,no,fields);
   const st=S.bundle.STEPS.find(x=>x.no===no);Object.assign(st,fields,{provenance:'manual'});toast('저장됨','ok');}
  catch(e){toast(e.message,'err');}}
 const rows=b.STEPS.map(s=>{
  const tr=h('tr',{class:blk.has(s.no)?'blocked':need.has(s.no)?'needs':''});
  const fld=k=>{const i=h('input',{class:'editf',value:s[k]??''});
   i.addEventListener('change',()=>save(s.no,{[k]:i.value}));return i;};
  const pts=h('div',{},...(s.pts||[]).map((pt,ix)=>{const i=h('input',{class:'editf',value:pt});
   i.addEventListener('change',()=>{const arr=[...s.pts];arr[ix]=i.value;save(s.no,{pts:arr});});return i;}),
   h('button',{class:'btn ghost',onclick:()=>save(s.no,{pts:[...(s.pts||[]),'']})},'+항목'));
  const rbtn=h('button',{class:'btn'},s.reviewed?'✓ 검수됨':'이 단계 검수 완료');
  rbtn.disabled=s.reviewed||blk.has(s.no);
  rbtn.onclick=async()=>{await API.reviewStep(S.job,s.no);go('review');};
  tr.append(h('td',{},String(s.no)),
   h('td',{},h('span',{class:'chip measured'},mmss(s.at)),' ',
    h('span',{class:'chip '+provChip(s.provenance)},s.provenance||'draft')),
   h('td',{},fld('badge')),h('td',{},fld('text')),h('td',{},fld('sub')),
   h('td',{},h('input',{class:'editf',type:'number',min:1,max:3,value:s.insp,
     onchange:e=>save(s.no,{insp:parseInt(e.target.value)})})),
   h('td',{},pts),h('td',{},rbtn));
  return tr;});
 $('#app').append(h('div',{class:'card'},h('h2',{},'④ 검수 · 라벨 편집'),banner,warn,
  h('div',{class:'tablewrap'},h('table',{},
   h('thead',{},h('tr',{},...['#','측정/출처','뱃지','작업','보조','검사','중점항목','검수'].map(x=>h('th',{},x)))),
   h('tbody',{},...rows))),
  h('button',{class:'btn',onclick:()=>go('approve')},'승인 단계로')));}

// ⑤ 승인·내보내기
async function renderApprove(my){const b=await API.bundle(S.job);if(my!==TOKEN)return;const r=b.review;
 const allReviewed=b.STEPS.length&&b.STEPS.every(s=>s.reviewed);
 const nameI=h('input',{class:'editf',placeholder:'서명자',value:'operator'});
 const apr=h('button',{class:'btn'},'승인');apr.disabled=!(r.evidence_ok&&allReviewed&&!r.approved);
 const exp=h('button',{class:'btn'},'내보내기 (zip)');exp.disabled=!r.approved;
 const out=h('div',{id:'expout'});
 apr.onclick=async()=>{try{await API.approve(S.job,nameI.value||'operator');toast('승인 완료 · 검증 반영','ok');go('approve');}
  catch(e){toast(e.message,'err');go('approve');}};
 exp.onclick=async()=>{try{const j=await API.export_(S.job);out.replaceChildren(
   h('a',{href:j.download,class:'btn'},'zip 다운로드'),h('div',{class:'mut'},j.path));}
  catch(e){toast(e.message,'err');}};
 $('#app').append(h('div',{class:'card'},h('h2',{},'⑤ 승인 · 내보내기'),
  h('div',{class:r.approved?'chip grounded':'bar-warn'},
   r.approved?('승인됨 · 서명자 '+(r.signed_by||'')+' · 검증 완료 · RAG 반영'):
   ('근거 '+(r.evidence_ok?'충족':'미충족')+' · 검수 '+countReviewed(b)+'/'+r.total_steps+' · 모든 단계 검수 후 승인')),
  h('div',{class:'row'},nameI,apr,exp),out));}
