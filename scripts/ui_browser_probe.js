(() => {
if (window !== window.top || window.__frProbe) return;
const p=window.__frProbe={events:[],messages:[],loads:{},frames:[],pending:null};
const ids=new WeakMap();let seq=0,activeFrame=null,activeDoc=null,activeMap=null,last=null;
const id=o=>{if(!o)return null;if(!ids.has(o))ids.set(o,++seq);return ids.get(o)};
const now=()=>performance.now();
const visible=e=>{if(!e)return false;const r=e.getBoundingClientRect();return r.width>0&&r.height>0&&r.bottom>0&&r.top<innerHeight&&getComputedStyle(e).visibility!=='hidden'};
const metrics=()=>[...document.querySelectorAll('[data-testid="stMetricValue"]')].map(e=>e.textContent).join('|');
const snapshot=()=>{const f=document.querySelector('iframe');let w,d,m;try{w=f?.contentWindow;d=f?.contentDocument;m=w?.map_div?.getCenter?w.map_div:w?.map?.getCenter?w.map:null;}catch{};if(!m||!m._loaded)return null;
const layers=Object.values(m._layers||{}), markers=layers.filter(l=>l.getLatLng&&l.options?.radius===7).map(l=>({color:l.options.color,point:[l.getLatLng().lat,l.getLatLng().lng],id:id(l)}));
const route=layers.filter(l=>l.options?.color==='#14834d');
const tiles=[...d.querySelectorAll('img.leaflet-tile')];
return {f,d,m,frame_id:id(f),document_id:id(d),map_id:id(m),container_id:id(m.getContainer()),zoom:m.getZoom(),center:[m.getCenter().lat,m.getCenter().lng],markers,route:route.length,route_ids:route.map(id),tiles:tiles.length,tiles_pending:tiles.filter(i=>!i.complete||!i.naturalWidth).length,route_revision:m.getContainer().dataset.routeRevision,ack:m.getContainer().dataset.ack,component_render_ms:Number(m.getContainer().dataset.componentRenderMs||0),backend_timing:m.getContainer().dataset.backendTiming,tile_requests:w.performance.getEntriesByType('resource').filter(r=>/tile.openstreetmap/.test(r.name)).length};};
const clean=s=>s?Object.fromEntries(Object.entries(s).filter(([k])=>!['f','d','m'].includes(k))):null;
const begin=(kind)=>{p.pending={kind,at:now(),before:clean(snapshot()),oldMetrics:metrics(),frames:0};};
document.addEventListener('click',e=>{if(e.target.closest('button')?.textContent.includes('开始规划'))begin('route_plan_visible_ms')},true);
const tick=()=>{try{
if(!p.loads.page_shell_visible_ms&&visible(document.querySelector('h1'))&&document.body.textContent.includes('规划条件'))p.loads.page_shell_visible_ms=now();
const s=snapshot();if(s){
if(s.d!==activeDoc){activeDoc=s.d;activeFrame=s.f;activeMap=s.m;p.frames.push({at:now(),frame_id:s.frame_id,document_id:s.document_id,map_id:s.map_id,container_id:s.container_id});s.f.contentWindow.addEventListener('message',e=>{if(e.data?.type==='streamlit:render'){const a=e.data.args||{};p.messages.push({at:now(),bytes:new TextEncoder().encode(JSON.stringify(a)).length,html_payload:typeof a.script==='string'||typeof a.html==='string',backend:a.timing||null});}});s.d.addEventListener('click',e=>{if(e.target.closest('.leaflet-control'))return;if(e.target.closest('.leaflet-container')){const label=[...document.querySelectorAll('input[type=radio]')].find(e=>e.checked)?.value||'';begin(label==='1'?'goal_click_feedback_ms':'start_click_feedback_ms')}},true);}
if(!p.loads.map_interactive_ms&&s.m.dragging?.enabled()&&s.m.getSize().x>0&&visible(s.f))p.loads.map_interactive_ms=now();
if(s.tiles>0&&!s.tiles_pending&&!p.loads.online_tile_complete_ms)p.loads.online_tile_complete_ms=now();
if(p.pending){let q=p.pending;const color=q.kind==='start_click_feedback_ms'?'#2474cf':'#e78222';let ready;
if(q.kind==='route_plan_visible_ms')ready=s.route>0&&metrics().split('|').length===7&&!metrics().includes('—')&&(JSON.stringify(s.route_ids)!==JSON.stringify(q.before?.route_ids)||metrics()!==q.oldMetrics||s.route_revision!==q.before?.route_revision);
else {const a=s.markers.find(x=>x.color===color),b=q.before?.markers.find(x=>x.color===color);ready=!!a&&JSON.stringify(a)!==JSON.stringify(b);}
if(ready){q.frames++;if(q.frames>=3){p.events.push({kind:q.kind,latency_ms:now()-q.at,started_ms:q.at,visible_ms:now(),before:q.before,after:clean(s),full_map_remount:s.map_id!==q.before?.map_id,iframe_remount:s.frame_id!==q.before?.frame_id,document_replaced:s.document_id!==q.before?.document_id,container_changed:s.container_id!==q.before?.container_id,tile_requests_delta:s.tile_requests-(q.before?.tile_requests||0),metrics:metrics(),render_messages:p.messages.filter(m=>m.at>=q.at)});p.pending=null;}}else q.frames=0;
}
last=clean(s);p.current=last;
}
}catch(e){p.error=String(e)}requestAnimationFrame(tick)};requestAnimationFrame(tick);
})();