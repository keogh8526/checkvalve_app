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
 export_:job=>api('POST','/api/export',{job}),
 getSettings:()=>api('GET','/api/settings'),
 setSettings:(model,api_key)=>api('POST','/api/settings',{model,api_key}),
 library:()=>api('GET','/api/library'),
 save:(job,name)=>api('POST','/api/save',{job,name}),
 prep:job=>api('GET','/api/prep?job='+encodeURIComponent(job))};
const SCREENS=['ingest','run','preview','review','approve'];
const RENDER={home:renderHome,prep:renderPrep,ingest:renderIngest,run:renderRun,preview:renderPreview,review:renderReview,approve:renderApprove,settings:renderSettings};
const go=n=>{const t='#/'+n;if(location.hash===t)route();else location.hash=t;};  // same-hash still re-renders
function setStep(n){const i=SCREENS.indexOf(n);
 [...$('#wizard').children].forEach((b,x)=>{b.classList.toggle('active',x===i);
  b.classList.toggle('done',x<i);b.classList.toggle('locked',x>=2&&!S.job);});
 const jp=$('#jobPill');if(S.job){jp.hidden=false;jp.textContent='작업 '+S.job.slice(-6);}else jp.hidden=true;}
async function route(){const my=++TOKEN;
 clearInterval(S.poll);S.poll=null;   // leaving any screen kills a live run-poll so it can't hijack navigation
 const n=(location.hash.slice(2)||'home').split('?')[0];
 if(n==='settings'||n==='home'){[...$('#wizard').children].forEach(b=>b.classList.remove('active'));
  $('#app').replaceChildren();
  const jp=$('#jobPill');if(n==='home')jp.hidden=true;
  try{await (n==='home'?renderHome:renderSettings)(my);}catch(e){if(my===TOKEN)$('#app').append(h('div',{class:'err'},'로드 실패: '+e.message));}
  return;}
 if(n==='prep'){[...$('#wizard').children].forEach(b=>b.classList.remove('active'));$('#app').replaceChildren();
  if(!S.job){toast('먼저 클립을 선택하세요','warn');return go('home');}
  try{await renderPrep(my);}catch(e){if(my===TOKEN)$('#app').append(h('div',{class:'err'},'전처리 로드 실패: '+e.message));}
  return;}
 const t=SCREENS.includes(n)?n:'ingest';
 if(t!=='ingest'&&t!=='run'&&!S.job){toast('먼저 클립을 생성하세요','warn');return go('run');}
 setStep(t);$('#app').replaceChildren();
 try{await RENDER[t](my);}catch(e){if(my===TOKEN)$('#app').append(h('div',{class:'err'},'화면 로드 실패: '+e.message));}}
document.addEventListener('DOMContentLoaded',()=>{
 $('#wizard').addEventListener('click',e=>{const b=e.target.closest('.wz');
  if(b&&!b.classList.contains('locked'))go(b.dataset.screen);});
 $('#gearBtn').addEventListener('click',()=>go('settings'));
 $('#homeBtn').addEventListener('click',()=>go('home'));
 window.addEventListener('hashchange',route);init();});

async function init(){S.job=sessionStorage.getItem('job')||null;
 try{const p=await API.parts();S.parts=p.parts||[];S.llm=!!p.llm_available;S.part_id=p.part_id||'';S.model=p.model||'';S.doc=p.doc||{};
  $('#partTag').textContent=' · '+S.part_id;}catch(e){}
 if(S.job){try{const st=await API.status(S.job);
   if(st.state==='error'||st.state==='unknown'){sessionStorage.removeItem('job');S.job=null;}
   else S.stem=st.stem||S.stem;}catch(e){sessionStorage.removeItem('job');S.job=null;}}
 route();}

// 홈 · 라이브러리
async function renderHome(my){
 let d={instructions:[]};try{d=await API.library();}catch(e){}
 try{const p=await API.parts();S.parts=p.parts||[];S.llm=!!p.llm_available;S.part_id=p.part_id||S.part_id;S.model=p.model||'';S.doc=p.doc||{};$('#partTag').textContent=' · '+(S.part_id||'');}catch(e){}
 if(my!==TOKEN)return;
 const newCard=h('div',{class:'card'},h('h2',{},'새 작업지도서'),
  h('div',{class:'row'},h('label',{},'조립 영상(mp4) '),h('input',{type:'file',accept:'video/mp4,.mp4',onchange:uploadVideo})),
  h('div',{id:'vidNote',class:'mut'}),
  h('div',{class:'row'},h('label',{},'공정 지침서 PDF (선택) '),h('input',{type:'file',accept:'application/pdf',onchange:uploadDoc})),
  h('div',{id:'docNote',class:'mut'},S.doc&&S.doc.parsed?('문서 반영됨 · '+(S.doc.chars||0)+'자'):''),
  h('p',{class:'mut'},S.llm?('Claude '+(S.model||'')+' 비전으로 분석합니다. 영상 업로드 후 ② 실행에서 생성하세요.')
   :h('span',{},'⚠ 생성하려면 먼저 ',h('a',{href:'#/settings'},'⚙ 설정에서 API 키'),'를 입력하세요.')));
 const CH={approved:'grounded',review:'rag',draft:'stub'},LB={approved:'승인완료',review:'검수중',draft:'초안'};
 const rows=(d.instructions||[]).map(it=>{
  const open=()=>{S.stem=it.stem;const part=(S.parts||[]).find(x=>x.stem===it.stem);
   S.job=(part&&part.last_job&&part.last_job.job_id)||it.stem;   // real job_id if we have one (survives reload); else bare stem
   sessionStorage.setItem('job',S.job);go(it.status==='approved'?'approve':'review');};
  return h('tr',{},
   h('td',{},it.thumb?h('img',{class:'evthumb',style:'width:64px;margin:0',src:'/output/'+encodeURIComponent(it.stem)+'/'+it.thumb,loading:'lazy'}):h('span',{class:'mut'},'—')),
   h('td',{},h('div',{},it.name),h('div',{class:'mut'},it.part+' · '+it.n_steps+'단계'+(it.reviewed?(' · 검수 '+it.reviewed+'/'+it.n_steps):'')+(it.signer?(' · 서명 '+it.signer):''))),
   h('td',{},h('span',{class:'chip '+(CH[it.status]||'stub')},LB[it.status]||it.status)),
   h('td',{},h('button',{class:'btn',onclick:open},it.status==='approved'?'열기':'이어서'),' ',
    h('button',{class:'btn ghost',onclick:()=>window.open('/api/preview?job='+encodeURIComponent(it.stem),'_blank')},'미리보기')));});
 const lib=h('div',{class:'card'},h('h2',{},'저장된 작업지도서'),
  (d.instructions||[]).length?h('div',{class:'tablewrap'},h('table',{},
   h('thead',{},h('tr',{},...['','이름','상태',''].map(x=>h('th',{},x)))),h('tbody',{},...rows)))
  :h('p',{class:'mut'},'아직 만든 지도서가 없습니다 — 위에서 영상을 올려 시작하세요.'));
 $('#app').replaceChildren(newCard,lib);}

// ② 전처리 확인 (키포인트 오버레이)
const COCO_EDGES=[['left_shoulder','right_shoulder'],['left_shoulder','left_elbow'],['left_elbow','left_wrist'],['right_shoulder','right_elbow'],['right_elbow','right_wrist'],['left_shoulder','left_hip'],['right_shoulder','right_hip'],['left_hip','right_hip'],['left_hip','left_knee'],['left_knee','left_ankle'],['right_hip','right_knee'],['right_knee','right_ankle'],['nose','left_shoulder'],['nose','right_shoulder']];
function drawSkeleton(cv,img,kp,res){const W=img.clientWidth,Hh=img.clientHeight;cv.width=W;cv.height=Hh;
 const ctx=cv.getContext('2d');ctx.clearRect(0,0,W,Hh);if(!kp||!res||!res[0])return;
 const sx=W/res[0],sy=Hh/res[1],T=0.2;ctx.lineWidth=2;ctx.strokeStyle='#1d9e75';ctx.fillStyle='#e24b4a';
 COCO_EDGES.forEach(([a,b])=>{const pa=kp[a],pb=kp[b];if(pa&&pb&&pa[2]>T&&pb[2]>T){ctx.beginPath();ctx.moveTo(pa[0]*sx,pa[1]*sy);ctx.lineTo(pb[0]*sx,pb[1]*sy);ctx.stroke();}});
 Object.values(kp).forEach(p=>{if(p&&p[2]>T){ctx.beginPath();ctx.arc(p[0]*sx,p[1]*sy,3,0,7);ctx.fill();}});}
async function renderPrep(my){const d=await API.prep(S.job);if(my!==TOKEN)return;
 const pf=d.profile||{},dg=d.digest||{},qc=d.qc||{},kfs=d.keyframes||[];
 const info=h('div',{class:'card'},h('div',{style:'font-weight:500;margin-bottom:6px'},'전처리 정보 (읽기)'),
   h('div',{class:'mut',style:'line-height:2'},
     '샷 유형: '+(pf.shot_type||'?')+' · 신호원 '+(dg.signal_source||'-'),h('br'),
     '몸체 신뢰 '+(pf.body_trust?'✓':'✕')+' · 손 신뢰 '+(pf.hand_trust?'✓':'✕'),h('br'),
     '길이 '+mmss(pf.duration_sec||0)+' · '+(pf.fps?pf.fps.toFixed(1):'?')+'fps',h('br'),
     '해상도 '+((d.resolution||[]).join('×')||'?'),h('br'),
     '모션 구간 '+(dg.n_segments||0)+'개 · 키프레임 '+kfs.length+'장',h('br'),
     'QC 불일치 '+(qc.disagree_pct!=null?qc.disagree_pct+'%':'-')+' · 미검출 '+(qc.no_detection_pct!=null?qc.no_detection_pct+'%':'-')));
 const big=h('img',{class:'prepbig'}),cv=h('canvas',{class:'prepcv'});
 const wrap=h('div',{class:'prepwrap'},big,cv),caps=h('div',{class:'mut'});
 let show=true,cur=kfs[0]||null;
 function select(f){cur=f;caps.textContent='프레임 t='+mmss(f.sec)+' · frame '+f.frame+(f.kp?'':' · 키포인트 미검출');
   big.onload=()=>drawSkeleton(cv,big,show?f.kp:null,d.resolution);
   big.src='/output/'+encodeURIComponent(d.stem)+'/'+f.path;if(big.complete)big.onload();}
 const toggle=h('label',{class:'mut'},h('input',{type:'checkbox',checked:'',onchange:e=>{show=e.target.checked;if(cur)drawSkeleton(cv,big,show?cur.kp:null,d.resolution);}}),' 키포인트 스켈레톤 표시');
 const strip=h('div',{class:'kfstrip'},...kfs.map(f=>h('img',{class:'kfthumb',src:'/output/'+encodeURIComponent(d.stem)+'/'+f.path,title:mmss(f.sec),onclick:()=>select(f)})));
 const right=kfs.length?h('div',{},h('div',{class:'row'},toggle),wrap,caps,strip):h('p',{class:'bar-warn'},'키프레임이 없습니다 — 먼저 ② 실행으로 생성하세요.');
 $('#app').append(h('div',{class:'card'},h('h2',{},'② 전처리 확인'),
   h('p',{class:'mut'},'추출된 키포인트·프레임을 확인합니다. 키프레임을 클릭하면 스켈레톤이 겹쳐 보입니다. (Claude는 이 프레임들을 분석합니다)'),
   h('div',{class:'prepsplit'},info,right),
   h('div',{class:'row'},h('button',{class:'btn',onclick:()=>go('run')},'자동 작업지도서 생성 →'),
     h('button',{class:'btn ghost',onclick:()=>go('review')},'④ 검수'),
     h('button',{class:'btn ghost',onclick:()=>go('home')},'← 홈'))));
 if(kfs.length)select(kfs[0]);   // draw AFTER append so a cache-hit img reports real clientWidth (not 0×0)
 const onResize=()=>{if(my!==TOKEN){window.removeEventListener('resize',onResize);return;}
   if(cur)drawSkeleton(cv,big,show?cur.kp:null,d.resolution);};   // keep the overlay aligned when the image reflows
 window.addEventListener('resize',onResize);}

// ① 수집
async function renderIngest(my){const d=await API.parts();if(my!==TOKEN)return;S.parts=d.parts;S.llm=!!d.llm_available;S.doc=d.doc||{};S.model=d.model||'';S.part_id=d.part_id||S.part_id;
 const pick=stem=>{S.stem=stem;S.job=null;sessionStorage.removeItem('job');go('run');};   // switching clip drops any stale job
 const rows=d.parts.map(p=>h('tr',{},
  h('td',{},p.stem.slice(-9)),h('td',{},p.shot_type),
  h('td',{},(p.roles||[]).join(', ')+(p.is_timeline?' ★타임라인':'')),
  h('td',{html:p.has_guide?'<span class="chip grounded">생성됨</span>':'—'}),
  h('td',{},h('button',{class:'btn',onclick:()=>pick(p.stem)},'선택'))));
 $('#app').append(
  h('div',{class:'card'},h('h2',{},'① 클립 수집 / 역할'),
   h('table',{},h('thead',{},h('tr',{},...['클립','샷','역할','지도서',''].map(x=>h('th',{},x)))),
    h('tbody',{},...rows)),
   h('p',{class:'bar-warn'},'역할은 수동 보정 가능. 아래에서 영상을 직접 올릴 수 있습니다.')),
  h('div',{class:'card'},h('h3',{},'영상 직접 업로드'),
   h('p',{class:'mut'},'mp4를 올리면 키포인트 전처리(YOLO·손·QC) 후 지도서를 생성합니다. 파일명이 클립 ID가 됩니다 (영문/숫자/_/- 만).'),
   h('input',{type:'file',accept:'video/mp4,.mp4',onchange:uploadVideo}),
   h('div',{id:'vidNote',class:'mut'})),
  h('div',{class:'card'},h('h3',{},'공정관리 지침서 PDF 업로드'),
   h('p',{class:'mut'},'업로드하면 텍스트를 추출해 Claude 분석의 근거로 사용합니다. 문서가 있으면 단계 내용·수치가 문서에 근거해 작성됩니다(없으면 모션만으로 추정).'),
   h('input',{type:'file',accept:'application/pdf',onchange:uploadDoc}),
   h('div',{id:'docNote',class:'mut'},S.doc&&S.doc.parsed?('현재: 문서 반영됨 · '+(S.doc.chars||0)+'자'):'현재: 문서 없음')));}
async function uploadVideo(e){const f=e.target.files[0];if(!f)return;
 const note=$('#vidNote');note.textContent='업로드 중… '+f.name;
 try{const r=await fetch('/api/upload?name='+encodeURIComponent(f.name),
   {method:'POST',headers:{'Content-Type':'video/mp4'},body:await f.arrayBuffer()});
  const j=await r.json();if(!r.ok)throw new Error(j.error||('HTTP '+r.status));
  note.textContent='업로드됨: '+j.stem+' ('+Math.round(j.bytes/1048576)+'MB)'+(j.replaced?' · 기존 키포인트 무효화됨':'');
  const p=await API.parts();S.parts=p.parts||[];S.stem=j.stem;S.job=null;sessionStorage.removeItem('job');
  toast('업로드 완료 — 생성하세요','ok');go('run');}
 catch(err){note.textContent='';toast('업로드 실패: '+err.message,'err');}}
async function uploadDoc(e){const f=e.target.files[0];if(!f)return;
 try{const r=await fetch('/api/doc?part_id='+encodeURIComponent(S.part_id),
  {method:'POST',headers:{'Content-Type':'application/pdf'},body:await f.arrayBuffer()});
  const j=await r.json();$('#docNote').textContent='저장됨: '+f.name+' · '+(j.spec?.note||'');}
 catch(err){toast('업로드 실패','err');}}

// ② 실행
async function renderRun(my){
 const p=S.parts.find(x=>x.stem===S.stem);
 if(!p){$('#app').append(h('div',{class:'card'},h('h2',{},'② 생성 실행'),
   h('p',{class:'bar-warn'},'대상 클립이 선택되지 않았습니다. 먼저 영상을 선택하거나 업로드하세요.'),
   h('div',{class:'row'},h('button',{class:'btn',onclick:()=>go('home')},'← 홈(라이브러리)'),
     h('button',{class:'btn ghost',onclick:()=>go('ingest')},'① 수집에서 선택'))));return;}   // no silent fallback to parts[0]
 S.stem=p.stem;const hasGuide=!!p.has_guide;
 const card=h('div',{class:'card'},h('h2',{},'② 생성 실행'),
  h('p',{},'대상 클립: ',h('b',{},S.stem.slice(-9)),p.is_timeline?' (타임라인)':'',
   hasGuide?h('span',{class:'chip grounded',style:'margin-left:8px'},'기존 결과 있음'):''),
  h('p',{class:'mut'},'직접 올린 영상은 키포인트 전처리(YOLO·손·QC)를 먼저 실행하며, 영상 길이에 따라 수 분 걸릴 수 있습니다. 이미 처리된 클립은 즉시 생성됩니다.'
   +(hasGuide?' 다시 생성하면 기존 지도서·검수 상태를 덮어씁니다.':'')));
 const docNote=(S.doc&&S.doc.parsed)?('공정지침서 반영 · '+(S.doc.chars||0)+'자 → 수치·용어 문서 근거'):'공정지침서 없음 → 영상 프레임 관찰 기반(수치는 PDF 업로드 권장)';
 const status=S.llm
  ? h('div',{class:'chip grounded'},'Claude '+(S.model||'')+' 비전으로 영상 키프레임 분석 · '+docNote)
  : h('div',{class:'bar-warn'},'Claude API 키가 필요합니다 (RAG 제거됨). ',h('a',{href:'#/settings'},'⚙ 설정에서 키 입력 →'));
 const btn=h('button',{class:'btn',onclick:start},hasGuide?'다시 생성 (덮어쓰기)':'작업지도서 생성 (Claude 분석)');btn.disabled=!S.llm;
 const row=h('div',{class:'row'},btn,h('button',{class:'btn ghost',onclick:()=>go('prep')},'전처리 확인 (키포인트)'));
 if(hasGuide)row.append(h('button',{class:'btn ghost',onclick:()=>window.open('/api/preview?job='+encodeURIComponent(S.stem),'_blank')},'기존 결과 보기'));
 const bar=h('div',{id:'runbar'});
 card.append(status,row,bar);$('#app').append(card);
 async function start(){btn.disabled=true;
  try{const {job_id}=await API.run(S.stem,true);S.job=job_id;sessionStorage.setItem('job',job_id);setStep('run');poll();}
  catch(e){btn.disabled=false;if(e.status===409){S.job=e.payload.job_id;sessionStorage.setItem('job',S.job);setStep('run');poll();}
   else toast(e.message,'err');}}
 function poll(){clearInterval(S.poll);
  S.poll=setInterval(async()=>{if(my!==TOKEN){clearInterval(S.poll);return;}
   let st;try{st=await API.status(S.job);}catch(e){return;}
   if(my!==TOKEN){clearInterval(S.poll);return;}   // user navigated away mid-request — don't touch the (detached) bar or navigate
   bar.replaceChildren(h('div',{},'상태: ',h('b',{},st.state),' · ',st.stage||'',' ',st.pct+'%'),
    h('pre',{class:'logtail'},(st.log_tail||[]).slice(-8).join('\n')));
   if(st.state==='done'){clearInterval(S.poll);toast('생성 완료','ok');go('preview');}
   if(st.state==='error'){clearInterval(S.poll);
    bar.append(h('div',{class:'err'},'생성 실패: '+(st.error||'')),h('button',{class:'btn',onclick:start},'재시도'));}},900);}
 // Resume polling ONLY for a job that (a) belongs to THIS clip and (b) is still in flight.
 // A finished/foreign/bare-stem job is dropped so the generate button stays usable (no auto-bounce to a stale preview).
 if(S.job){const owner=S.job.includes('.')?S.job.slice(0,S.job.lastIndexOf('.')):null;
  const drop=()=>{S.job=null;sessionStorage.removeItem('job');if(my===TOKEN)setStep('run');};
  if(owner!==S.stem){drop();}
  else{API.status(S.job).then(st=>{if(my!==TOKEN)return;
    if(st.state==='queued'||st.state==='running')poll();else drop();}).catch(()=>drop());}}}

// ③ 미리보기
async function renderPreview(my){const p=S.parts.find(x=>x.stem===S.stem);
 const wrap=h('div',{class:'card'},h('h2',{},'③ 미리보기 · 작업지도서 (영상 재생 시 단계가 시간에 따라 표시)'));
 const url=()=>'/api/preview?job='+encodeURIComponent(S.job)+'&t='+Date.now();
 const fr=h('iframe',{title:'deliverable'});fr.src=url();
 wrap.append(
  h('p',{class:'mut'},'아래 지도서에서 ▶ 재생을 누르면 영상 시각에 맞춰 현재 단계가 형광펜으로 강조되고 캡션이 바뀝니다. 크게 보려면 [새 탭에서 열기].'),
  h('div',{class:'row'},
   h('button',{class:'btn',onclick:()=>window.open('/api/preview?job='+encodeURIComponent(S.job),'_blank')},'⛶ 새 탭에서 크게 열기'),
   h('button',{class:'btn ghost',onclick:()=>{fr.src=url();}},'↺ 새로고침'),
   h('button',{class:'btn ghost',onclick:()=>go('review')},'④ 검수로 →')),
  h('div',{class:'iframewrap tall'},fr));
 $('#app').append(wrap);}

// ④ 검수·라벨편집
function countReviewed(b){return b.STEPS.filter(s=>s.reviewed).length;}
async function renderReview(my){const b=await API.bundle(S.job);if(my!==TOKEN)return;S.bundle=b;
 const need=new Set(b.review.needs_review||[]),blk=new Set(b.review.blocked||[]);   // evidence-based, static across a review
 const groundChip=g=>({'pdf':'grounded','visual':'rag','inferred':'stub'}[g]||'rag');
 const groundLbl=g=>({'pdf':'문서근거','visual':'영상근거','inferred':'추정'}[g]||(g||''));
 const evUrl=im=>'/output/'+encodeURIComponent(b.stem)+'/'+im;
 const rbtnByNo={};
 // banner refreshed in place from S.bundle.review + live reviewed-count (no full re-render → scroll kept)
 const banner=h('div',{});
 function paintBanner(){const r=S.bundle.review;
  banner.className=r.approved?'chip grounded':r.evidence_ok?'bar-warn':'err';
  banner.textContent=r.approved?'승인 완료':r.evidence_ok?('근거 충족 · 서명 대기 · 검수 '+countReviewed(S.bundle)+'/'+r.total_steps):
   ('미승인 · 검수 '+(r.needs_review||[]).length+'건');}
 paintBanner();
 const warn=(b.review.warnings||[]).length?h('details',{class:'warnbox'},
   h('summary',{},'⚠ 자동 보정·경고 '+b.review.warnings.length+'건 (승인은 막지 않음 · 펼치기)'),
   h('ul',{class:'warns'},...b.review.warnings.map(w=>h('li',{},w)))):'';
 // per-step promise chain: serialize PUTs and apply SERVER truth only after it resolves; revert focus on failure.
 const saveChains={};
 function save(no,fields){
  saveChains[no]=(saveChains[no]||Promise.resolve()).then(async()=>{
   const res=await API.putStep(S.job,no,fields);
   const st=S.bundle.STEPS.find(x=>x.no===no);
   Object.assign(st,res.step||fields,{provenance:'manual',reviewed:false});   // editing revokes this step's sign-off (server did too)
   if(res.review)S.bundle.review=res.review;                                   // whole-guide approval may have been revoked
   const rb=rbtnByNo[no];if(rb){rb.disabled=blk.has(no);rb.textContent='검수 완료';}
   paintBanner();if(focused&&focused.no===no)setFocus(focused);toast('저장됨','ok');
  }).catch(e=>{if(focused&&focused.no===no)setFocus(focused);toast(e.message,'err');});   // failed PUT → show server truth, not the rejected edit
  return saveChains[no];}
 // left: live focus preview of the selected step (frame + rendered content)
 let focused=b.STEPS[0];
 const focus=h('div',{class:'card focusprev'});
 function setFocus(s){focused=s;focus.replaceChildren(
   h('div',{class:'mut'},'미리보기 · 단계 '+s.no+' · '+mmss(s.at)),
   s.image?h('img',{src:evUrl(s.image),class:'focusimg'}):h('div',{class:'focusimg mut',style:'display:flex;align-items:center;justify-content:center'},'프레임 없음'),
   h('div',{style:'font-weight:700;margin-top:6px'},s.badge||'미정'),
   h('div',{},s.text||''),h('div',{class:'mut'},s.sub||''),
   h('ul',{style:'margin:6px 0 0;padding-left:18px'},...(s.pts||[]).map(p=>h('li',{class:'mut'},p))));}
 // right: editable step cards
 const cards=b.STEPS.map(s=>{
  const card=h('div',{class:'stepcard'+(blk.has(s.no)?' blocked':need.has(s.no)?' needs':'')});
  const fld=(k,ph)=>{const i=h('input',{class:'editf',value:s[k]??'',placeholder:ph});
   i.addEventListener('change',()=>save(s.no,{[k]:i.value}));return i;};
  const ptsWrap=h('div',{});
  const renderPts=()=>ptsWrap.replaceChildren(...(s.pts||[]).map((pt,ix)=>{const i=h('input',{class:'editf',value:pt});
    i.addEventListener('change',()=>{const arr=[...(s.pts||[])];arr[ix]=i.value;save(s.no,{pts:arr});});return i;}),   // no optimistic local mutation — apply on resolve
    h('button',{class:'btn ghost',onclick:()=>{const arr=[...(s.pts||[]),''];save(s.no,{pts:arr}).then(()=>renderPts());}},'+ 중점항목'));
  renderPts();
  const rbtn=h('button',{class:'btn'},s.reviewed?'✓ 검수됨':'검수 완료');
  rbtn.disabled=s.reviewed||blk.has(s.no);rbtnByNo[s.no]=rbtn;
  rbtn.onclick=async(e)=>{e.stopPropagation();rbtn.disabled=true;   // disable before await → no double-submit
   try{const res=await API.reviewStep(S.job,s.no);
    const st=S.bundle.STEPS.find(x=>x.no===s.no);if(st)st.reviewed=true;s.reviewed=true;
    if(res.review)S.bundle.review=res.review;
    rbtn.textContent='✓ 검수됨';paintBanner();toast('검수됨','ok');   // in place: scroll & focus preserved
   }catch(err){rbtn.disabled=false;toast(err.message,'err');}};
  const thumb=s.image?h('img',{class:'evthumb',style:'width:110px;margin:0',src:evUrl(s.image),
    onclick:e=>{e.stopPropagation();window.open(evUrl(s.image),'_blank');}}):h('div',{class:'mut'},'프레임 없음');
  card.append(h('div',{style:'display:flex;gap:10px'},thumb,
    h('div',{style:'flex:1;min-width:0'},
      h('div',{style:'display:flex;gap:6px;align-items:center;margin-bottom:5px'},
        h('span',{class:'chip measured'},mmss(s.at)),
        h('span',{class:'chip '+groundChip(s.grounding)},s.grounding?groundLbl(s.grounding):(s.provenance||'draft')),
        h('span',{class:'mut',style:'margin-left:auto'},'단계 '+s.no)),
      fld('badge','뱃지'),fld('text','작업 내용 및 방법'),fld('sub','보조 설명'),
      h('div',{class:'row',style:'margin-top:5px'},h('span',{class:'mut'},'검사'),
        h('input',{class:'editf',type:'number',min:1,max:3,value:s.insp,style:'width:52px',onchange:e=>save(s.no,{insp:parseInt(e.target.value)||1})}),
        rbtn),
      h('div',{class:'mut',style:'margin-top:6px'},'중점 관리 항목'),ptsWrap)));
  card.addEventListener('click',()=>setFocus(s));
  return card;});
 setFocus(focused);
 $('#app').append(h('div',{class:'card'},h('h2',{},'④ 검수 · 편집'),
  h('div',{class:'row'},banner,
   h('button',{class:'btn ghost',onclick:()=>go('preview')},'③ 시간동기화 미리보기'),
   h('button',{class:'btn ghost',onclick:()=>window.open('/api/preview?job='+encodeURIComponent(S.job),'_blank')},'⛶ 전체 새 창')),
  warn,
  h('p',{class:'mut'},'카드를 클릭하면 왼쪽에 근거 프레임과 내용이 뜹니다. 각 단계 검수 완료 후 ⑤로.'),
  h('div',{class:'reviewsplit'},h('div',{},focus),h('div',{class:'stepcards'},...cards)),
  h('button',{class:'btn',onclick:()=>go('approve')},'⑤ 완료·저장으로 →')));}

// ⑤ 완료 · 저장
async function renderApprove(my){const b=await API.bundle(S.job);if(my!==TOKEN)return;const r=b.review;
 const allReviewed=b.STEPS.length&&b.STEPS.every(s=>s.reviewed);
 const nameD=h('input',{class:'editf',placeholder:'지도서 이름 (예: 체크밸브 조립 v1)',value:(b.meta&&b.meta.name)||''});
 const nameI=h('input',{class:'editf',placeholder:'서명자',value:r.signed_by||'operator',style:'max-width:150px'});
 const saveB=h('button',{class:'btn ghost'},'이름 저장');
 saveB.onclick=async()=>{try{await API.save(S.job,nameD.value||'');toast('저장됨','ok');}catch(e){toast(e.message,'err');}};
 const apr=h('button',{class:'btn'},'현장 확정 (승인)');apr.disabled=!(r.evidence_ok&&allReviewed&&!r.approved);
 const exp=h('button',{class:'btn'},'zip 내보내기');exp.disabled=!r.approved;
 const openB=h('button',{class:'btn ghost'},'⛶ 새 창으로 열기');
 openB.onclick=()=>window.open('/api/preview?job='+encodeURIComponent(S.job),'_blank');
 const out=h('div',{id:'expout'});
 apr.onclick=async()=>{try{if(nameD.value)await API.save(S.job,nameD.value);await API.approve(S.job,nameI.value||'operator');toast('현장 확정 완료','ok');go('approve');}
  catch(e){toast(e.message,'err');go('approve');}};
 exp.onclick=async()=>{try{const j=await API.export_(S.job);out.replaceChildren(
   h('a',{href:j.download,class:'btn'},'zip 다운로드'),h('div',{class:'mut'},j.path));}
  catch(e){toast(e.message,'err');}};
 $('#app').append(h('div',{class:'card'},h('h2',{},'⑤ 완료 · 저장'),
  h('div',{class:r.approved?'chip grounded':'bar-warn'},
   r.approved?('승인됨 · 서명자 '+(r.signed_by||'')+' · 라이브러리에 승인완료로 저장'):
   ('근거 '+(r.evidence_ok?'충족':'미충족')+' · 검수 '+countReviewed(b)+'/'+r.total_steps+' · 모든 단계 검수 후 확정')),
  h('div',{class:'row'},h('label',{},'이름 '),nameD,saveB),
  h('div',{class:'row'},h('label',{},'서명자 '),nameI,apr,exp,openB),out,
  h('div',{class:'row'},h('button',{class:'btn ghost',onclick:()=>go('home')},'← 홈(라이브러리)'))));}

// ⚙ Claude API 설정 (마법사 밖)
async function renderSettings(my){const s=await API.getSettings();if(my!==TOKEN)return;
 const sel=h('select',{class:'editf'},...s.models.map(m=>h('option',{value:m},m)));sel.value=s.model;
 const keyI=h('input',{class:'editf',type:'password',autocomplete:'off',
  placeholder:s.has_key?('현재 '+s.key_hint+' · 변경 시에만 입력'):'sk-ant-api03-...'});
 const save=h('button',{class:'btn'},'저장');
 const clr=h('button',{class:'btn ghost'},'키 삭제');
 save.onclick=async()=>{try{const k=keyI.value.trim();await API.setSettings(sel.value,k||undefined);
   const p=await API.parts();S.llm=!!p.llm_available;S.model=p.model||'';keyI.value='';toast('설정 저장됨','ok');go('settings');}
  catch(e){toast(e.message,'err');}};
 clr.onclick=async()=>{try{await API.setSettings(sel.value,'');S.llm=false;toast('키 삭제됨','ok');go('settings');}
  catch(e){toast(e.message,'err');}};
 $('#app').append(h('div',{class:'card'},h('h2',{},'⚙ Claude API 설정'),
  h('p',{class:'mut'},'모델과 API 키를 설정합니다. 키는 이 PC의 홈 폴더(~/.checkvalve/settings.json)에만 저장되며 저장소에 커밋되지 않습니다.'),
  h('div',{class:'row'},h('label',{},'모델 '),sel),
  h('div',{class:'row'},h('label',{},'API 키 '),keyI),
  h('div',{},h('span',{class:s.has_key?'chip grounded':'bar-warn'},
   s.has_key?('키 설정됨 · '+s.key_hint+' · 모델 '+s.model):'키 미설정 — RAG 모드로만 동작')),
  h('div',{class:'row'},save,clr),
  h('p',{class:'mut'},'② 실행에서 "Claude 사용"을 켜면 이 모델(기본 Sonnet 5)로 단계를 조직합니다. 키가 없으면 내장 골드 풀(RAG)로 동작합니다.')));}
