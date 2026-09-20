// One map for the entire iframe lifetime. All later renders are JSON layer updates.
(() => {
  const post = (type, extra={}) => parent.postMessage({isStreamlitMessage:true,type,...extra}, '*');
  let map, args, route, routeKey=null, tile, roads, roadPromise, eventId=0, fitted=null;
  const markers={start:null,goal:null}, root=document.getElementById('map_div');
  const afterPaint = fn => requestAnimationFrame(()=>requestAnimationFrame(fn));
  function setMarker(k,p) {
    if (!p) {if(markers[k])map.removeLayer(markers[k]);markers[k]=null;return;}
    const ll=[p.lat,p.lng];
    if(markers[k]) markers[k].setLatLng(ll);
    else markers[k]=L.circleMarker(ll,{radius:7,color:k==='start'?'#2474cf':'#e78222',fill:true,fillOpacity:1}).bindTooltip(k==='start'?'起点':'终点').addTo(map);
  }
  function setTileMode(online) {
    if(online) {
      if(roads&&map.hasLayer(roads))map.removeLayer(roads);
      if(!tile) {
        tile=L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png',{attribution:'&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'});
        tile.on('loading',()=>{root.dataset.tileLoadingAt=String(performance.now());});
        tile.on('load',()=>{root.dataset.tileCompleteAt=String(performance.now());});
      }
      if(!map.hasLayer(tile))tile.addTo(map);
    } else {
      if(tile&&map.hasLayer(tile))map.removeLayer(tile);
      if(roads) {if(!map.hasLayer(roads))roads.addTo(map);}
      else if(!roadPromise) roadPromise=fetch('roads_display.geojson').then(r=>{if(!r.ok)throw Error(r.status);return r.json();}).then(data=>{
        roads=L.geoJSON(data,{style:{color:'#a1a8ac',weight:1,opacity:.65},interactive:false});
        if(!args.online)roads.addTo(map);
      }).catch(()=>{root.dataset.roadsError='true';roadPromise=null;});
    }
  }
  addEventListener('message', e=>{
    if(e.source!==parent||e.data.type!=='streamlit:render')return;
    args=e.data.args; const received=performance.now();
    if(!map) {
      map=L.map(root,{preferCanvas:true}).setView(args.center,args.zoom);
      window.map_div=map; // Diagnostic handle; no business state is kept here.
      L.control.scale().addTo(map);
      map.on('click',e=>{
        const b=map.getBounds();
        post('streamlit:setComponentValue',{value:{last_clicked:{lat:e.latlng.lat,lng:e.latlng.lng},
          bounds:{_southWest:{lat:b.getSouth(),lng:b.getWest()},_northEast:{lat:b.getNorth(),lng:b.getEast()}},
          zoom:map.getZoom(),request_id:++eventId,selection:args.selection},dataType:'json'});
      });
      new ResizeObserver(()=>map.invalidateSize({pan:false})).observe(root);
      document.getElementById('loading').remove();
    }
    setTileMode(args.online);
    setMarker('start',args.markers.start);setMarker('goal',args.markers.goal);
    const nextKey=JSON.stringify(args.route);
    if(nextKey!==routeKey) {
      if(route)map.removeLayer(route);
      route=args.route?L.geoJSON(args.route,{style:{color:'#14834d',weight:5},interactive:false}).addTo(map):null;
      routeKey=nextKey;
    }
    if(args.route&&args.bounds&&fitted!==args.revision){map.fitBounds(args.bounds,{padding:[40,40],maxZoom:16,animate:false});fitted=args.revision;}
    root.dataset.renderReceivedAt=String(received);
    afterPaint(()=>{
      root.dataset.routeRevision=args.revision;
      root.dataset.ack=String(args.timing.request_id||0);
      root.dataset.componentRenderMs=String(performance.now()-received);
      root.dataset.backendTiming=JSON.stringify(args.timing);
    });
    post('streamlit:setFrameHeight',{height:560});
  });
  post('streamlit:componentReady',{apiVersion:1});
  post('streamlit:setFrameHeight',{height:560});
})();
