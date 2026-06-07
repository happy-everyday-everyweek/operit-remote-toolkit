/* 从content_raw中提取工具调用列表 */
function parseToolCalls(raw){
  if(!raw)return [];
  var calls=[];var rgx=/<tool\s+name="([^"]+)"[^>]*>[\s\S]*?<\/tool>/g;var m;
  while((m=rgx.exec(raw))!== null){
    var name=m[1];
    var full=m[0];
    var params='';
    var pm=/<param\s+name="([^"]+)">([\s\S]*?)<\/param>/g;var p;
    while((p=pm.exec(full))!== null){
      var val=p[2].trim().substring(0,60);
      if(val.length>=60)val+='...';
      params+='<div class="tp-row"><span class="tp-key">'+p[1]+'</span><span class="tp-val">'+escapeHtml(val)+'</span></div>';
    }
    calls.push({name:name,content:full,paramsHtml:params});
  }
  return calls;
}

function escapeHtml(s){
  if(!s)return '';
  return s.replace(/&/g,'&').replace(/</g,'<').replace(/>/g,'>').replace(/"/g,'"');
}

/* 将 file:// 本地图片路径转为 HTTP 可访问路径 */
function resolveLocalImage(src){
  if(!src)return src;
  // 如果已经是绝对或相对 HTTP URL，不做处理
  if(src.startsWith('http://')||src.startsWith('https://')||src.startsWith('//'))return src;
  // 处理 file:// 开头
  if(src.startsWith('file://')){
    var path=src.slice(7); // 去掉 file://
    return '/file/'+encodeURIComponent(path);
  }
  // 处理 /开头的绝对路径（如 /storage/emulated/0/...）
  if(src.startsWith('/')){
    return '/file/'+encodeURIComponent(src);
  }
  return src;
}

/* 文本中的链接转为分屏链接 */
function linkifyText(text){
  if(!text)return '';
  var urlRgx=/(https?:\/\/[^\s<>"']+)/g;
  return text.replace(urlRgx,function(m){
    var d=m.length>60?m.slice(0,57)+'...':m;
    return '<a href="javascript:void(0)" onclick="window.openSplitUrl(\''+m.replace(/'/g,"\\'")+'\',\''+d.replace(/'/g,"\\'")+'\')" class="split-link">'+d+'</a>';
  });
}

/* Markdown转HTML */
function mdToHtml(text){
  if(!text)return '';
  // 先处理图片 Markdown：![alt](file:///xxx) 或 ![alt](/xxx)
  var html=text
    .replace(/!\[([^\]]*)\]\(\s*(file:\/\/[^\s)]+)\s*\)/g,function(m,alt,src){
      return '<img src="'+resolveLocalImage(src)+'" alt="'+alt.replace(/"/g,'"')+'" style="max-width:100%;border-radius:6px;margin:6px 0" loading="lazy">';
    })
    .replace(/!\[([^\]]*)\]\(\s*(\/[^\s)]+)\s*\)/g,function(m,alt,src){
      return '<img src="'+resolveLocalImage(src)+'" alt="'+alt.replace(/"/g,'"')+'" style="max-width:100%;border-radius:6px;margin:6px 0" loading="lazy">';
    });
  html=html
    .replace(/```(\w*)\n?([\s\S]*?)```/g,'<pre><code>$2</code></pre>')
    .replace(/`([^`]+)`/g,'<code>$1</code>')
    .replace(/\*\*([^*]+)\*\*/g,'<strong>$1</strong>')
    .replace(/\*([^*]+)\*/g,'<em>$1</em>')
    .replace(/~~([^~]+)~~/g,'<del>$1</del>')
    .replace(/^### (.+)$/gm,'<h4>$1</h4>')
    .replace(/^## (.+)$/gm,'<h3>$1</h3>')
    .replace(/^# (.+)$/gm,'<h2>$1</h2>')
    .replace(/^> (.+)$/gm,'<blockquote>$1</blockquote>')
    .replace(/^[-*] (.+)$/gm,'<li>$1</li>')
    .replace(/^\d+\.\s+(.+)$/gm,'<li>$1</li>')
    .replace(/\n/g,'<br>');
  return linkifyText(html);
}

/* 获取纯文本（去掉xml工具调用标签） */
function getCleanText(m){
  var text='';
  if(m.display_content){text=m.display_content;}
  else if(m.content_blocks&&m.content_blocks.length>0){
    text=m.content_blocks.filter(function(b){return b.kind==='text'}).map(function(b){return b.content||''}).join('').trim();
  }
  if(!text&&m.content_raw){text=m.content_raw.replace(/<tool[^>]*>[\s\S]*?<\/tool>/g,'').trim();}
  return text;
}

/* 渲染消息内容：纯文本 + 工具调用卡片 */
function renderMessageContent(m,streaming){
  var container=document.createElement('div');
  // 渲染纯文本
  var text=getCleanText(m);
  var textHtml=mdToHtml(text);
  if(textHtml){var td=document.createElement('div');td.innerHTML=textHtml;container.appendChild(td);}
  // 渲染工具调用卡片
  var tools=parseToolCalls(m.content_raw||'');
  for(var i=0;i<tools.length;i++){
    (function(tool){
      var card=document.createElement('div');
      card.className='tool-card';
      // 头部：工具名 + 展开按钮
      var head=document.createElement('div');
      head.className='tc-head';
      head.innerHTML='<span class="tc-icon">></span><span class="tc-name">'+tool.name+'</span><span class="tc-arrow">></span>';
      // 参数摘要
      var body=document.createElement('div');
      body.className='tc-body';
      body.innerHTML=tool.paramsHtml;
      // 折叠面板（完整XML）
      var detail=document.createElement('div');
      detail.className='tc-detail';
      detail.textContent=tool.content;
      // 切换展开/收起
      var expanded=false;
      head.onclick=function(){
        expanded=!expanded;
        body.style.display=expanded?'block':'none';
        detail.style.display=expanded?'block':'none';
        head.querySelector('.tc-arrow').style.transform=expanded?'rotate(90deg)':'rotate(0deg)';
      };
      card.appendChild(head);
      card.appendChild(body);
      card.appendChild(detail);
      container.appendChild(card);
    })(tools[i]);
  }
  if(streaming){var cur=document.createElement('span');cur.className='delta-cursor';cur.textContent=' ▍';container.appendChild(cur);}
  return container;
}
