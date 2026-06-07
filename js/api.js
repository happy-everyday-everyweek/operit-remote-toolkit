var BASE='http://'+location.hostname+':8094';
var TOKEN='b1a9f1e4f24742deb5bd1fa9afe97179';

async function apiJson(path,init){
  var resp=await fetch(BASE+path,{...init,headers:{Accept:'application/json','Content-Type':'application/json',Authorization:'Bearer '+TOKEN,...(init?.headers||{})}});
  var text=await resp.text();var data;
  try{data=JSON.parse(text)}catch{data={}}
  if(!resp.ok)throw new Error(data.error||'HTTP '+resp.status);
  return data;
}

function formatTime(ts){
  var ms=ts>100000000000?ts:ts*1000;
  var d=new Date(ms);
  if(isNaN(d.getTime()))return '--:--';
  var pad=function(n){return String(n).padStart(2,'0')};
  return pad(d.getHours())+':'+pad(d.getMinutes());
}

function parseSSE(block){
  var lines=block.split(/\r?\n/);var name='';var data=[];
  for(var i=0;i<lines.length;i++){var l=lines[i];if(l.startsWith('event:'))name=l.slice(6).trim();else if(l.startsWith('data:'))data.push(l.slice(5))}
  if(!name||data.length===0)return void 0;
  try{return{event:name,...JSON.parse(data.join('\n'))}}catch{return void 0}
}
