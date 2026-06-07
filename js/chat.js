var currentChatId=void 0,messages=[],chats=[],sending=false,loadingMore=false,hasMoreBefore=false,nextBeforeTs=void 0,abortController=void 0;
var messagesEl=document.getElementById('messages'),msgInput=document.getElementById('msg-input'),sendBtn=document.getElementById('send-btn');
var chatTitle=document.getElementById('chat-title'),overlay=document.getElementById('chat-list-overlay');
var chatListContent=document.getElementById('chat-list-content'),newChatBtn=document.getElementById('new-chat-btn');

function scrollBottom(){setTimeout(function(){messagesEl.scrollTop=messagesEl.scrollHeight},50)}

function getChatName(c){return c.title||c.id.slice(0,8)}

function updateChatTitle(){chatTitle.textContent=chats.find(function(c){return c.id===currentChatId})?getChatName(chats.find(function(c){return c.id===currentChatId})):'选择对话'}

function showChatList(){
  chatListContent.innerHTML='';
  for(var i=0;i<chats.length;i++){
    var c=chats[i];
    var div=document.createElement('div');div.className='chat-item'+(c.id===currentChatId?' active':'');
    var name=document.createElement('span');name.textContent=getChatName(c);div.appendChild(name);
    (function(cid){
      var del=document.createElement('span');del.className='del-btn';del.textContent='×';
      del.onclick=async function(e){e.stopPropagation();if(!confirm('删除该对话？'))return;try{await apiJson('/api/web/chats/'+cid,{method:'DELETE'});chats=chats.filter(function(x){return x.id!==cid});if(cid===currentChatId){if(chats.length>0){switchChat(chats[0].id)}else{currentChatId=void 0;messages=[];renderMessages();updateChatTitle()}}showChatList()}catch(e){}};
      div.appendChild(del);
      div.onclick=function(){switchChat(cid);hideChatList()};
    })(c.id);
    chatListContent.appendChild(div);
  }
  overlay.classList.add('show');
}

function hideChatList(){overlay.classList.remove('show')}

async function switchChat(id){
  if(id===currentChatId)return;
  try{await apiJson('/api/web/chats/'+id,{method:'PUT',body:JSON.stringify({set_current:true})})}catch(e){}
  currentChatId=id;updateChatTitle();await loadMessages(id);
}

function renderMessages(){
  var ps=messagesEl.scrollTop,ph=messagesEl.scrollHeight;
  messagesEl.innerHTML='';
  if(hasMoreBefore){var d=document.createElement('div');d.id='load-more';d.textContent='加载更多';d.onclick=loadMoreMessages;messagesEl.appendChild(d)}
  for(var i=0;i<messages.length;i++){var m=messages[i];var div=document.createElement('div');
    if(m.sender==='user'||m.sender==='assistant'){div.className='msg '+m.sender;var c=renderMessageContent(m,m.streaming);div.appendChild(c);var t=document.createElement('div');t.className='time';t.textContent=formatTime(m.timestamp);div.appendChild(t);}
    else{div.className='msg system';div.textContent=m.content_raw||''}
    messagesEl.appendChild(div);}
  if(ps>0&&ph>0)requestAnimationFrame(function(){messagesEl.scrollTop=messagesEl.scrollHeight-ph+ps});else scrollBottom();
}

async function loadMoreMessages(){
  if(loadingMore||!hasMoreBefore||!nextBeforeTs)return;
  loadingMore=true;
  var el=document.getElementById('load-more');if(el)el.textContent='加载中';
  try{
    var data=await apiJson('/api/web/chats/'+encodeURIComponent(currentChatId)+'/messages?limit=30&before_timestamp='+nextBeforeTs);
    var old=data.messages||[];hasMoreBefore=data.has_more_before||false;nextBeforeTs=data.next_before_timestamp||void 0;
    var exist=new Set(messages.map(function(m){return m.id}));messages=[].concat(old.filter(function(m){return !exist.has(m.id)})).concat(messages);renderMessages();
  }catch(e){if(el)el.textContent='加载更多'}
  loadingMore=false;
}

async function loadMessages(chatId){
  messagesEl.innerHTML='<div id="status">加载中</div>';
  try{
    var data=await apiJson('/api/web/chats/'+encodeURIComponent(chatId)+'/messages?limit=50');
    messages=data.messages||[];hasMoreBefore=data.has_more_before||false;nextBeforeTs=data.next_before_timestamp||void 0;
    renderMessages();
  }catch(e){messagesEl.innerHTML='<div id="status">加载失败</div>'}
}

async function sendMessage(text){
  if(sending||!text.trim()||!currentChatId)return;
  sending=true;msgInput.disabled=true;sendBtn.disabled=true;msgInput.placeholder='发送中';
  abortController=new AbortController();
  var userMsg={id:'tmp-u'+Date.now(),sender:'user',content_raw:text,display_content:text,timestamp:Math.floor(Date.now()/1000)};
  messages.push(userMsg);renderMessages();scrollBottom();
  var aiMsg={id:'tmp-a'+Date.now(),sender:'assistant',content_raw:'',display_content:'',timestamp:Math.floor(Date.now()/1000),streaming:true};
  messages.push(aiMsg);renderMessages();scrollBottom();
  try{
    var resp=await fetch(BASE+'/api/web/chats/'+encodeURIComponent(currentChatId)+'/messages/stream',{
      method:'POST',headers:{Authorization:'Bearer '+TOKEN,Accept:'text/event-stream','Content-Type':'application/json'},
      body:JSON.stringify({message:text,attachment_ids:[],return_tool_status:true}),signal:abortController.signal
    });
    if(!resp.ok){var t=await resp.text();var m='失败';try{m=JSON.parse(t).error||m}catch{}throw new Error(m)}
    var reader=resp.body.getReader(),decoder=new TextDecoder();var buffer='';
    while(true){
      var result=await reader.read();if(result.done)break;
      buffer+=decoder.decode(result.value,{stream:true});
      var blocks=buffer.split(/\r?\n\r?\n/);buffer=blocks.pop()||'';
      for(var j=0;j<blocks.length;j++){var b=blocks[j];var ev=parseSSE(b.trim());if(!ev)continue;
        if(ev.event==='assistant_delta'&&ev.delta){
          var last=messages[messages.length-1];
          if(last&&last.streaming){
            last.content_raw+=ev.delta;last.display_content=last.content_raw.replace(/<tool[^>]*>[\s\S]*?<\/tool>/g,'');
            var els=messagesEl.querySelectorAll('.msg'),el=els[els.length-1];
            if(el&&el.classList.contains('assistant')){var ce=el.querySelector('div:first-child');if(ce){var nc=renderMessageContent(last,true);ce.parentNode.replaceChild(nc,ce);}}
            scrollBottom();
          }
        }else if(ev.event==='assistant_done'){
          var last=messages[messages.length-1];
          if(last){last.streaming=false;if(ev.message){last.id=ev.message.id;last.content_raw=ev.message.content_raw;last.display_content=ev.message.display_content||ev.message.content_raw.replace(/<tool[^>]*>[\s\S]*?<\/tool>/g,'');last.timestamp=ev.message.timestamp}}
          renderMessages();scrollBottom();
        }else if(ev.event==='error'){throw new Error(ev.error||'错误')}
      }
    }
    if(buffer){var ev=parseSSE(buffer.trim());if(ev&&ev.event==='assistant_done'){var last=messages[messages.length-1];if(last){last.streaming=false;if(ev.message){last.id=ev.message.id;last.content_raw=ev.message.content_raw;last.display_content=ev.message.display_content||ev.message.content_raw.replace(/<tool[^>]*>[\s\S]*?<\/tool>/g,'');last.timestamp=ev.message.timestamp}}renderMessages();scrollBottom()}}
  }catch(e){
    if(e.name==='AbortError')return;var last=messages[messages.length-1];if(last&&last.streaming)messages.pop();
    messages.push({id:'err'+Date.now(),sender:'system',content_raw:e.message});renderMessages();scrollBottom();
  }
  sending=false;msgInput.disabled=false;sendBtn.disabled=false;msgInput.placeholder='输入消息';msgInput.focus();
}

// 事件绑定
chatTitle.onclick=function(){showChatList()};
document.getElementById('chat-list-bg').onclick=function(){hideChatList()};
newChatBtn.onclick=async function(){
  try{var nc=await apiJson('/api/web/chats',{method:'POST',body:JSON.stringify({set_current:true})});chats.unshift(nc);await switchChat(nc.id);hideChatList();}catch(e){}
};
// 斜杠命令提示 - 确保初始隐藏
var slashHint=document.getElementById('slash-hint');
if(slashHint)slashHint.style.display='none';
var slashItems=document.querySelectorAll('.slash-item');

function showSlashHint(){
  if(slashHint)slashHint.style.display='block';
}
function hideSlashHint(){
  if(slashHint)slashHint.style.display='none';
}

// 点击命令项
slashItems.forEach(function(item){
  item.onclick=function(e){
    e.stopPropagation();
    var cmd=item.getAttribute('data-command');
    hideSlashHint();
    executeCommand(cmd);
  };
});

function executeCommand(cmd){
  if(cmd==='/tool'){
    msgInput.value='';msgInput.style.height='auto';hideSlashHint();
    var base=window.location.origin||window.location.protocol+'//'+window.location.host;
    openSplitUrl(base+'/toolbox.html','工具箱');
  }
}

// 检测斜杠命令
function checkCommand(text){
  var t=text.trim();
  if(t==='/tool'||t==='/tools'){
    executeCommand('/tool');
    return true;
  }
  return false;
}

// 发送按钮
sendBtn.onclick=function(){
  var t=msgInput.value;
  if(!t.trim()||sending)return;
  if(checkCommand(t)){
    hideSlashHint();
    return;
  }
  msgInput.value='';msgInput.style.height='auto';
  hideSlashHint();
  sendMessage(t);
};

// 输入框键盘事件
msgInput.onkeydown=function(e){
  if(e.key==='Enter'&&!e.shiftKey){
    e.preventDefault();
    if(checkCommand(msgInput.value)){
      hideSlashHint();
      return;
    }
    hideSlashHint();
    if(!sending&&msgInput.value.trim()){
      sendBtn.click();
    }
  }
  if(e.key==='Escape'){hideSlashHint()}
};

// 输入框内容变化时控制面板显示
msgInput.oninput=function(){
  this.style.height='auto';this.style.height=Math.min(this.scrollHeight,80)+'px';
  var val=this.value;
  if(val==='/'){
    showSlashHint();
  }else{
    hideSlashHint();
  }
};

// 点击面板外部隐藏
document.addEventListener('click',function(e){
  if(slashHint&&slashHint.style.display==='block'&&!slashHint.contains(e.target)&&e.target!==msgInput){
    hideSlashHint();
  }
});

// 初始化
(async function(){
  try{
    var boot=await apiJson('/api/web/bootstrap');
    chats=await apiJson('/api/web/chats');
    if(boot.current_chat_id&&chats.some(function(c){return c.id===boot.current_chat_id})){currentChatId=boot.current_chat_id}
    else if(chats.length>0){currentChatId=chats[0].id}
    else{var nc=await apiJson('/api/web/chats',{method:'POST',body:JSON.stringify({set_current:true})});currentChatId=nc.id;chats=[nc]}
    updateChatTitle();
    if(currentChatId){msgInput.disabled=false;sendBtn.disabled=false;await loadMessages(currentChatId)}
  }catch(e){messagesEl.innerHTML='<div id="status">连接失败</div>'}
})();
