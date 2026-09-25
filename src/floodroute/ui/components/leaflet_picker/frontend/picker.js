// One L.Map for the iframe lifetime. Static geometry loads once; reruns send values only.
(() => {
  const post = (type, extra={}) => parent.postMessage({isStreamlitMessage:true,type,...extra}, '*');
  const root=document.getElementById('map_div'), markers={start:null,goal:null};
  const rainColors=['#d9edf7','#a6cee3','#4aa8d8','#fee08b','#f46d43','#a50026'];
  const riskColors=['#2ca25f','#99d8c9','#fee08b','#fdae61','#d73027'];
  let map,args,route,routeKey=null,tile,roads,roadPromise,eventId=0,fitted=null,queryMarker;
  let gridLayer,gridPromise,riskLayer,riskPromise,sensorLayer,rainValues=new Map(),riskValues=new Map();
  let rainLegend,riskLegend,feedbackSamples=[];
  const afterPaint = fn => requestAnimationFrame(()=>requestAnimationFrame(fn));
  const valueText = v => v===null||v===undefined||Number.isNaN(Number(v))?'暂无可靠数据':Number(v).toFixed(3);
  const escapeHtml = value => String(value).replace(/[&<>'"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));

  function viewport(){const b=map.getBounds();return {
    bounds:{_southWest:{lat:b.getSouth(),lng:b.getWest()},_northEast:{lat:b.getNorth(),lng:b.getEast()}},
    zoom:map.getZoom()};}
  function sendClick(latlng,extra={}){
    root.dataset.clickSentAt=String(performance.now());
    root.dataset.clickKind=extra.road_edge_id?'road_query':args.selection;
    post('streamlit:setComponentValue',{value:{
      last_clicked:{lat:latlng.lat,lng:latlng.lng},request_id:++eventId,selection:args.selection,
      ...viewport(),...extra},dataType:'json'});
  }
  function setMarker(kind,point) {
    if(!point){if(markers[kind])map.removeLayer(markers[kind]);markers[kind]=null;return;}
    const ll=[point.lat,point.lng];
    if(markers[kind])markers[kind].setLatLng(ll);
    else markers[kind]=L.circleMarker(ll,{pane:'markerPane',radius:7,color:kind==='start'?'#2474cf':'#e78222',fill:true,fillOpacity:1})
      .bindTooltip(kind==='start'?'起点':'终点').addTo(map);
  }
  function setQueryMarker(point){
    if(!point){if(queryMarker)map.removeLayer(queryMarker);queryMarker=null;return;}
    const ll=[point.lat,point.lon];
    if(queryMarker)queryMarker.setLatLng(ll);
    else queryMarker=L.circleMarker(ll,{pane:'markerPane',radius:6,color:'#7b3294',weight:2,fillColor:'#c2a5cf',fillOpacity:.9})
      .bindTooltip('当前查询位置').addTo(map);
  }
  function setTileMode(online) {
    if(online) {
      if(roads&&map.hasLayer(roads))map.removeLayer(roads);
      if(!tile){
        tile=L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png',{attribution:'&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'});
        tile.on('loading',()=>{root.dataset.tileLoadingAt=String(performance.now());});
        tile.on('load',()=>{root.dataset.tileCompleteAt=String(performance.now());});
      }
      if(!map.hasLayer(tile))tile.addTo(map);
    } else {
      if(tile&&map.hasLayer(tile))map.removeLayer(tile);
      if(roads){if(!map.hasLayer(roads))roads.addTo(map);}
      else if(!roadPromise)roadPromise=fetch('roads_display.geojson').then(r=>{if(!r.ok)throw Error(r.status);return r.json();}).then(data=>{
        roads=L.geoJSON(data,{pane:'offlinePane',style:{color:'#a1a8ac',weight:1,opacity:.65},interactive:false});
        if(!args.online)roads.addTo(map);
      }).catch(()=>{root.dataset.roadsError='true';roadPromise=null;});
    }
  }
  function legend(title,rows){
    const control=L.control({position:'bottomright'});control.onAdd=()=>{const div=L.DomUtil.create('div','map-legend');
      div.innerHTML='<strong>'+title+'</strong>'+rows.map(r=>'<div><i style="background:'+r[0]+'"></i>'+r[1]+'</div>').join('');return div;};return control;
  }
  function updateGridLayer(){
    if(!gridLayer)return;
    gridLayer.eachLayer(layer=>{const item=rainValues.get(String(layer.feature.properties.grid_id));
      const level=item?item[1]:-1,value=item?item[0]:null;
      layer.setStyle({fillColor:level<0?'#bdbdbd':rainColors[level],fillOpacity:level<0?.12:.42,color:'#777',weight:.35});
      layer.bindPopup('<b>格网编号：</b>'+escapeHtml(layer.feature.properties.grid_id)+'<br><b>近1小时累计降雨：</b>'+
        (value===null?'暂无可靠数据':Number(value).toFixed(1)+' mm')+
        '<br><b>数据时间：</b>'+escapeHtml(args.rainMeta.timestamp||'暂无可靠数据')+
        '<br><b>数据来源：</b>'+escapeHtml(args.rainMeta.source||'暂无可靠数据')+
        '<br><small>地图显示分级，不代表灾害等级。</small>');});
  }
  function setRainLayer(enabled,data){
    root.dataset.rainEnabled=String(enabled);
    rainValues=new Map(data.map(x=>[String(x[0]),[x[1],x[2]]]));
    if(!enabled){if(gridLayer&&map.hasLayer(gridLayer))map.removeLayer(gridLayer);if(rainLegend){map.removeControl(rainLegend);rainLegend=null;}return;}
    if(!rainLegend){rainLegend=legend('降雨量（mm）',rainColors.map((c,i)=>[c,['0','0–10','10–25','25–50','50–100','>100'][i]]));rainLegend.addTo(map);}
    if(gridLayer){if(!map.hasLayer(gridLayer))gridLayer.addTo(map);updateGridLayer();return;}
    if(!gridPromise)gridPromise=fetch('grid_cells_display.geojson').then(r=>{if(!r.ok)throw Error(r.status);return r.json();}).then(data=>{
      gridLayer=L.geoJSON(data,{pane:'rainPane',style:{weight:.35},onEachFeature:(feature,layer)=>layer.on('click',()=>{})});
      if(args.layers.rain)gridLayer.addTo(map);updateGridLayer();
      root.dataset.gridGeometryLoads=String(Number(root.dataset.gridGeometryLoads||0)+1);
    }).catch(()=>{root.dataset.gridError='true';gridPromise=null;});
  }
  function updateRiskLayer(){
    if(!riskLayer)return;
    riskLayer.eachLayer(layer=>{const item=riskValues.get(layer.feature.properties.edge_id),level=item?item[1]:-1,risk=item?item[0]:null;
      layer.setStyle({color:level<0?'#969696':riskColors[level],weight:3,opacity:level<0?.25:.82});
      layer.bindTooltip('道路内涝风险指数：'+valueText(risk),{sticky:true});});
  }
  function setRoadRiskLayer(enabled,data){
    root.dataset.riskEnabled=String(enabled);
    riskValues=new Map(data.map(x=>[String(x[0]),[x[1],x[2]]]));
    if(!enabled){if(riskLayer&&map.hasLayer(riskLayer))map.removeLayer(riskLayer);if(riskLegend){map.removeControl(riskLegend);riskLegend=null;}return;}
    if(!riskLegend){riskLegend=legend('道路内涝风险指数',riskColors.map((c,i)=>[c,['低','较低','中等','较高','高'][i]]));riskLegend.addTo(map);}
    if(riskLayer){if(!map.hasLayer(riskLayer))riskLayer.addTo(map);updateRiskLayer();if(route)route.bringToFront();return;}
    if(!riskPromise)riskPromise=fetch('risk_roads_display.geojson').then(r=>{if(!r.ok)throw Error(r.status);return r.json();}).then(data=>{
      riskLayer=L.geoJSON(data,{pane:'riskPane',style:{weight:3},bubblingMouseEvents:false,onEachFeature:(feature,layer)=>{
        layer.on('click',e=>{if(e.originalEvent)L.DomEvent.stopPropagation(e.originalEvent);
          sendClick(e.latlng,{road_edge_id:feature.properties.edge_id});});}});
      if(args.layers.road_risk)riskLayer.addTo(map);updateRiskLayer();if(route)route.bringToFront();
      root.dataset.riskGeometryLoads=String(Number(root.dataset.riskGeometryLoads||0)+1);
    }).catch(()=>{root.dataset.riskError='true';riskPromise=null;});
  }
  function setSensorLayer(enabled,data){
    root.dataset.sensorEnabled=String(enabled);root.dataset.sensorCount=String(data.length);
    if(sensorLayer){map.removeLayer(sensorLayer);sensorLayer=null;}
    if(!enabled)return;
    sensorLayer=L.layerGroup();
    data.forEach(item=>{
      const unavailable=item.value===null||item.value===undefined;
      const value=unavailable?null:Number(item.value);
      const color=unavailable?'#8c8c8c':value>=.7?'#d73027':value>=.4?'#fdae61':'#2b83ba';
      const marker=L.circleMarker([item.lat,item.lon],{pane:'markerPane',radius:5,color:'#222',weight:1,fillColor:color,fillOpacity:.9});
      marker.bindPopup('<b>模拟积涝监测点：</b>'+escapeHtml(item.sensor_id)+
        '<br><b>积涝状态指数：</b>'+(unavailable?'暂无可靠数据':value.toFixed(3))+
        '<br><b>观测时间：</b>'+escapeHtml(item.timestamp||'暂无可靠数据')+
        '<br><b>到达时间：</b>'+escapeHtml(item.retrieved_at||'暂无可靠数据')+
        '<br><b>信息年龄：</b>'+(item.age_min===null?'暂无可靠数据':Number(item.age_min).toFixed(0)+' 分钟')+
        '<br><b>质量：</b>'+escapeHtml(item.quality)+'<br><b>状态：</b>'+escapeHtml(item.availability)+
        '<br><b>类型：</b>'+escapeHtml(item.source_type)+
        '<br><small>该数据为受控模拟积涝状态指数，不代表真实道路积水深度。</small>');
      marker.on('click',e=>{if(e.originalEvent)L.DomEvent.stopPropagation(e.originalEvent);});marker.addTo(sensorLayer);
    });sensorLayer.addTo(map);
  }

  addEventListener('message',e=>{
    if(e.source!==parent||e.data.type!=='streamlit:render')return;
    args=e.data.args;const received=performance.now();root.dataset.selection=args.selection;
    if(!map){
      map=L.map(root,{preferCanvas:true}).setView(args.center,args.zoom);window.map_div=map;
      root.dataset.mapInstanceId='leaflet-'+Math.random().toString(36).slice(2);
      map.createPane('offlinePane').style.zIndex=250;map.createPane('rainPane').style.zIndex=350;
      map.createPane('riskPane').style.zIndex=410;map.createPane('routePane').style.zIndex=450;
      L.control.scale().addTo(map);map.on('click',e=>sendClick(e.latlng));
      new ResizeObserver(()=>map.invalidateSize({pan:false})).observe(root);document.getElementById('loading').remove();
    }
    setTileMode(args.online);setRainLayer(!!args.layers.rain,args.rainData||[]);
    setRoadRiskLayer(!!args.layers.road_risk,args.roadRiskData||[]);
    setSensorLayer(!!args.layers.sensors,args.sensorData||[]);
    setMarker('start',args.markers.start);setMarker('goal',args.markers.goal);setQueryMarker(args.queryPoint);
    const nextKey=JSON.stringify(args.route);
    if(nextKey!==routeKey){if(route)map.removeLayer(route);route=args.route?L.geoJSON(args.route,{pane:'routePane',style:{color:'#14834d',weight:5},interactive:false}).addTo(map):null;routeKey=nextKey;}
    if(route)route.bringToFront();
    if(args.route&&args.bounds&&fitted!==args.revision){map.fitBounds(args.bounds,{padding:[40,40],maxZoom:16,animate:false});fitted=args.revision;}
    root.dataset.renderReceivedAt=String(received);root.dataset.rainValueCount=String((args.rainData||[]).length);
    root.dataset.riskValueCount=String((args.roadRiskData||[]).length);
    afterPaint(()=>{const painted=performance.now();root.dataset.routeRevision=args.revision;
      root.dataset.ack=String(args.timing.request_id||0);
      root.dataset.componentRenderMs=String(painted-received);root.dataset.backendTiming=JSON.stringify(args.timing);
      if(Number(args.timing.request_id||0)===eventId && root.dataset.clickSentAt &&
         root.dataset.recordedAck!==String(eventId)){
        const feedback=painted-Number(root.dataset.clickSentAt);
        root.dataset.lastFeedbackMs=String(feedback);
        root.dataset.lastFeedbackKind=root.dataset.clickKind||'';
        root.dataset.recordedAck=String(eventId);
        feedbackSamples.push({request_id:eventId,kind:root.dataset.clickKind||'',ms:feedback,
          component_render_ms:painted-received,backend:args.timing});
        root.dataset.feedbackSamples=JSON.stringify(feedbackSamples.slice(-50));
      }});
    post('streamlit:setFrameHeight',{height:560});
  });
  post('streamlit:componentReady',{apiVersion:1});post('streamlit:setFrameHeight',{height:560});
})();
