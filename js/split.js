/* ===== 分屏浏览 ===== */

function getSplitElems(){
  return {
    overlay: document.getElementById('split-overlay'),
    iframe: document.getElementById('split-iframe'),
    code: document.getElementById('split-code'),
    title: document.querySelector('#split-overlay .split-title'),
    close: document.querySelector('#split-overlay .split-close')
  };
}

function applySplitLayout(){
  var e=getSplitElems();
  var cp=document.getElementById('chat-page');
  if(!e.overlay||!cp)return;
  if(window.matchMedia('(orientation:landscape)').matches){
    cp.style.width='50%';
    cp.style.height='100%';
    cp.style.float='left';
    e.overlay.style.width='50%';
    e.overlay.style.height='100%';
    e.overlay.style.top='0';
    e.overlay.style.right='0';
    e.overlay.style.bottom='auto';
    e.overlay.style.left='auto';
  }else{
    cp.style.width='100%';
    cp.style.height='50%';
    cp.style.float='none';
    e.overlay.style.width='100%';
    e.overlay.style.height='50%';
    e.overlay.style.top='auto';
    e.overlay.style.right='auto';
    e.overlay.style.bottom='0';
    e.overlay.style.left='0';
  }
  e.overlay.style.display='flex';
  e.overlay.style.position='fixed';
}

function openSplitView(){
  var e=getSplitElems();
  if(e.overlay.classList.contains('show')){
    applySplitLayout();
    return;
  }
  e.overlay.classList.add('show');
  applySplitLayout();
}

function openSplitUrl(url,title){
  openSplitView();
  var e=getSplitElems();
  e.code.style.display='none';
  e.iframe.style.display='block';
  e.iframe.src=url;
  e.title.textContent=title||url;
}

function openSplitCode(content,title){
  openSplitView();
  var e=getSplitElems();
  e.iframe.style.display='none';
  e.iframe.src='about:blank';
  e.code.style.display='block';
  e.code.textContent=content;
  e.title.textContent=title||'详情';
}

function closeSplitView(){
  var e=getSplitElems();
  e.overlay.classList.remove('show');
  e.overlay.style.cssText='';
  e.iframe.style.display='none';
  e.iframe.src='about:blank';
  e.code.style.display='none';
  e.code.textContent='';
  var cp=document.getElementById('chat-page');
  cp.style.cssText='';
}

function bindSplitEvents(){
  var closeBtn=document.querySelector('#split-overlay .split-close');
  if(closeBtn)closeBtn.onclick=closeSplitView;
}
if(document.readyState==='loading'){
  document.addEventListener('DOMContentLoaded',bindSplitEvents);
}else{
  bindSplitEvents();
}

window.addEventListener('resize',function(){
  var e=getSplitElems();
  if(!e.overlay||!e.overlay.classList.contains('show'))return;
  applySplitLayout();
});

window.openSplitUrl=openSplitUrl;
window.openSplitCode=openSplitCode;
