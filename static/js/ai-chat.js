(function(){
  if(window.__AI_CHAT_INITIALIZED__) return;
  window.__AI_CHAT_INITIALIZED__=true;

  // AI 面板关键图标使用内联 SVG/文字：不依赖 FontAwesome 字体，
  // 避免客户端字体被拦截/缓存异常时图标变成彩色方块看不清。
  var AI_ROBOT_SVG='<svg class="ai-robot-svg" viewBox="0 0 24 24" fill="none" '+
    'stroke="currentColor" stroke-width="2" stroke-linecap="round" '+
    'stroke-linejoin="round" aria-hidden="true">'+
    '<rect x="4" y="8" width="16" height="12" rx="3"></rect>'+
    '<path d="M12 4v4M8 14h.01M16 14h.01M9 18h6"></path></svg>';

  var chatState={
    open:false,
    sessionId:'',
    usePageContext:true,
    pageContextDefault:true,
    sending:false,
    initialized:false,
    lastUserMessage:'',
    configMode:'admin',
    studentConfigured:false,
    isAdmin:false,
    isTeacherEdit:false,
    canSelfConfig:false,
    teacherConfigured:false,
    imageEnabled:false,
    imageMode:false,
    optimizeImage:false,
    lastRequestImage:false,
    visionEnabled:false,
    lastImages:[],
    deepseekTools:false,     // 官方 DeepSeek + deepseek-flash：显示联网/文件/语音入口
    webSearch:false,
    readUrl:true,
    files:[],                // 待发送的 DeepSeek 文件引用
    uploading:0,
    voiceId:'stella',
    ttsAudio:null,
    ttsUrl:'',
    recording:null,
    pageOnly:false,          // 学生端：教师已限定仅围绕当前页面内容
    canControlPageOnly:false,// 教师/管理员：可切换上述限定
    studentPageOnly:false,   // 教师/管理员视角：限定当前是否开启
    models:[],
    selectedModel:'',
    skills:null,             // 选中的教学技能 id；null 表示尚未读取本地选择
    skillsMeta:[],           // 服务端返回的技能元数据
    mdReady:false          // marked.js + highlight.js 就绪标志
  };

  var SKILL_STORAGE_KEY='aiSelectedSkills';
  // 服务端 /api/ai/status 未返回技能元数据时的兜底（正常部署不会走到）
  var SKILL_FALLBACK=[
    {id:'feynman',name:'费曼式简化解释',short:'费曼简化',description:'先讲本质，再用类比和分步解释；默认开启',default:true},
    {id:'socratic',name:'苏格拉底式提问',short:'苏格拉底提问',description:'不直接给答案，用问题引导使用者自己发现',default:false},
    {id:'antivibe',name:'代码审计式学习',short:'代码审计',description:'按结构、取舍和验证方式读懂一段代码',default:false}
  ];

  /* ──── 初始化 ──── */
  function init(){
    if(chatState.initialized) return;
    chatState.initialized=true;
    chatState.skills=readStoredSkills();

    fetch('/api/ai/status').then(function(r){return r.json();}).then(function(data){
      if(!data.enabled||!data.logged_in) return;
      chatState.pageContextDefault=data.page_context_default!==false;
      chatState.usePageContext=chatState.pageContextDefault;
      chatState.configMode=data.config_mode||'admin';
      chatState.studentConfigured=!!data.student_configured;
      chatState.isAdmin=!!data.is_admin;
      chatState.isTeacherEdit=!!data.is_teacher_edit;
      chatState.canSelfConfig=!!data.can_self_config;
      chatState.teacherConfigured=!!data.teacher_configured;
      chatState.imageEnabled=!!data.image_enabled;
      chatState.visionEnabled=!!data.vision_enabled;
      chatState.deepseekTools=!!data.deepseek_tools;
      try{
        var voice=localStorage.getItem('aiDeepseekVoice');
        if(voice==='stella'||voice==='tide') chatState.voiceId=voice;
      }catch(e){}
      chatState.pageOnly=!!data.page_only_enforced;
      if(chatState.pageOnly) chatState.usePageContext=true;
      chatState.canControlPageOnly=!!data.can_control_page_only;
      chatState.studentPageOnly=!!data.student_page_only;
      chatState.skillsMeta=normalizeSkillMeta(data.skills);
      var defaults=Array.isArray(data.default_skills)&&data.default_skills.length
        ? data.default_skills : ['feynman'];
      if(chatState.skills===null){
        chatState.skills=sanitizeSkillIds(defaults,chatState.skillsMeta);
      }else{
        chatState.skills=resolveStoredSkills(
          chatState.skills,chatState.skillsMeta,defaults);
      }
      createWidget();
      loadModels();
    }).catch(function(){});
  }
  /* ──── 教学技能选择（默认费曼式简化解释，可多选/全不选） ──── */
  function readStoredSkills(){
    try{
      var raw=localStorage.getItem(SKILL_STORAGE_KEY);
      if(raw===null) return null;          // 从未选择过 → 使用服务端默认
      var arr=JSON.parse(raw);
      return Array.isArray(arr)?arr:[];
    }catch(e){ return null; }
  }

  function normalizeSkillMeta(list){
    if(!Array.isArray(list)||!list.length) return SKILL_FALLBACK.slice();
    var out=[];
    list.forEach(function(m){
      if(!m||typeof m.id!=='string'||!m.id) return;
      out.push({
        id:m.id,
        name:String(m.name||m.id),
        short:String(m.short||m.name||m.id),
        description:String(m.description||''),
        default:!!m.default
      });
    });
    return out.length?out:SKILL_FALLBACK.slice();
  }

  function sanitizeSkillIds(ids,meta){
    var valid={};
    meta.forEach(function(m){ valid[m.id]=true; });
    var out=[];
    (Array.isArray(ids)?ids:[]).forEach(function(id){
      if(typeof id==='string'&&valid[id]&&out.indexOf(id)<0) out.push(id);
    });
    return out;
  }

  function resolveStoredSkills(stored,meta,defaults){
    var clean=sanitizeSkillIds(stored,meta);
    if(stored&&stored.length&&!clean.length) return sanitizeSkillIds(defaults,meta);
    return clean;
  }

  function saveSelectedSkills(){
    try{ localStorage.setItem(SKILL_STORAGE_KEY,JSON.stringify(chatState.skills||[])); }catch(e){}
  }

  function skillMetaById(id){
    for(var i=0;i<chatState.skillsMeta.length;i++){
      if(chatState.skillsMeta[i].id===id) return chatState.skillsMeta[i];
    }
    return null;
  }

  function skillNames(){
    return (chatState.skills||[]).map(function(id){
      var m=skillMetaById(id); return m?m.name:id;
    });
  }

  function skillButtonText(){
    var ids=chatState.skills||[];
    if(!ids.length) return '技能：不使用';
    if(ids.length===1){
      var m=skillMetaById(ids[0]);
      return '技能：'+(m?m.short:ids[0]);
    }
    return '技能：'+ids.length+' 项';
  }

  function toggleSkillMenu(force){
    var menu=document.getElementById('aiSkillMenu');
    var btn=document.getElementById('aiSkillBtn');
    if(!menu) return;
    var show=typeof force==='boolean'?force:!menu.classList.contains('show');
    menu.classList.toggle('show',show);
    if(btn) btn.setAttribute('aria-expanded',show?'true':'false');
  }

  function closeSkillMenu(){ toggleSkillMenu(false); }

  function renderSkillMenu(){
    var menu=document.getElementById('aiSkillMenu');
    if(!menu) return;
    if(!chatState.skillsMeta.length) chatState.skillsMeta=SKILL_FALLBACK.slice();
    var ids=chatState.skills||[];
    var html='<div class="ai-skill-menu-title">教学技能<span>可多选 · 仅影响后续回复</span></div>';
    chatState.skillsMeta.forEach(function(m){
      var checked=ids.indexOf(m.id)>=0;
      html+='<label class="ai-skill-item">'+
        '<input type="checkbox" data-skill="'+escapeHtml(m.id)+'"'+(checked?' checked':'')+'>'+
        '<span class="ai-skill-copy">'+
          '<span class="ai-skill-name">'+escapeHtml(m.name)+
            (m.default?'<span class="ai-skill-default">默认</span>':'')+'</span>'+
          '<span class="ai-skill-desc">'+escapeHtml(m.description)+'</span>'+
        '</span></label>';
    });
    html+='<div class="ai-skill-menu-foot">'+
      '<button type="button" id="aiSkillClear" class="ai-skill-foot-btn">不使用技能</button>'+
      '<button type="button" id="aiSkillDone" class="ai-skill-foot-btn primary">完成</button>'+
      '</div>';
    menu.innerHTML=html;
  }

  function renderSkillSummary(){
    var label=document.getElementById('aiSkillLabel');
    var btn=document.getElementById('aiSkillBtn');
    if(label) label.textContent=skillButtonText();
    if(btn){
      var names=skillNames();
      btn.title=names.length
        ? '教学技能：'+names.join('、')+'（点击选择，可多选）'
        : '当前不使用教学技能（点击选择）';
    }
  }

  function bindSkillMenu(panel){
    var btn=panel.querySelector('#aiSkillBtn');
    var menu=panel.querySelector('#aiSkillMenu');
    if(!btn||!menu) return;
    renderSkillMenu();
    renderSkillSummary();
    btn.addEventListener('click',function(e){
      e.stopPropagation();
      toggleSkillMenu();
    });
    menu.addEventListener('click',function(e){
      e.stopPropagation();
      var id=e.target&&e.target.id;
      if(id==='aiSkillClear'){
        chatState.skills=[];
        saveSelectedSkills();
        renderSkillMenu();
        renderSkillSummary();
      }else if(id==='aiSkillDone'){
        closeSkillMenu();
      }
    });
    menu.addEventListener('change',function(e){
      if(!e.target||!e.target.getAttribute) return;
      var sid=e.target.getAttribute('data-skill');
      if(!sid) return;
      if(e.target.checked){
        if(chatState.skills.indexOf(sid)<0) chatState.skills.push(sid);
      }else{
        chatState.skills=chatState.skills.filter(function(x){return x!==sid;});
      }
      var order={};
      chatState.skillsMeta.forEach(function(m,i){ order[m.id]=i; });
      chatState.skills.sort(function(a,b){ return (order[a]||0)-(order[b]||0); });
      saveSelectedSkills();
      renderSkillSummary();
    });
    document.addEventListener('click',function(){ closeSkillMenu(); });
    document.addEventListener('keydown',function(e){
      if(e.key==='Escape') closeSkillMenu();
    });
  }

  /* ──── Markdown 引擎加载（使用 resourceLoader 统一多源回退）── */
  function loadMarkdownEngine(){
    // 优先使用 resourceLoader 的多级回退（本地→BootCDN→Staticfile→Baomitu→Elemecdn→jsDelivr）
    var loader = window.resourceLoader;
    var loadMarked, loadHljs;

    if (loader && loader.tryLoadByType) {
      loadMarked = loader.tryLoadByType('marked');
      loadHljs = loader.tryLoadByType('hljs');
    } else {
      loadMarked = new Promise(function(resolve) {
        loadScriptFallback([
          '/static/marked/marked.min.js',
          'https://cdn.bootcdn.net/ajax/libs/marked/12.0.2/marked.min.js',
          'https://cdn.jsdelivr.net/npm/marked@12.0.2/marked.min.js'
        ], resolve, 'sha384-/TQbtLCAerC3jgaim+N78RZSDYV7ryeoBCVqTuzRrFec2akfBkHS7ACQ3PQhvMVi');
      });
      loadHljs = new Promise(function(resolve) {
        loadScriptFallback([
          '/static/highlight/highlight.min.js',
          'https://cdn.bootcdn.net/ajax/libs/highlight.js/11.9.0/highlight.min.js',
          'https://cdn.jsdelivr.net/npm/@highlightjs/cdn-assets@11.9.0/highlight.min.js'
        ], resolve, 'sha384-F/bZzf7p3Joyp5psL90p/p89AZJsndkSoGwRpXcZhleCWhd8SnRuoYo4d0yirjJp');
      });
    }

    Promise.all([loadMarked, loadHljs]).then(function() {
      initMarkdown();
    }).catch(function() {
      initMarkdown(); // 即使全部失败也初始化（降级纯文本）
    });

    // 兜底：3s 后强制初始化
    setTimeout(function(){ if(!chatState.mdReady) initMarkdown(); }, 3000);
  }

  function loadScriptFallback(urls, resolve, integrity) {
    var nextIndex = 0;
    function next() {
      if (nextIndex >= urls.length) { resolve(); return; }
      var url = urls[nextIndex++];
      var s = document.createElement('script');
      var done = false;
      s.async = false;
      s.src = url;
      if (/^https?:/.test(url)) {
        s.crossOrigin = 'anonymous';
        s.integrity = integrity;
      }
      var timer = setTimeout(fail, 5000);
      function fail() {
        if (done) return;
        done = true;
        clearTimeout(timer);
        s.remove();
        if (navigator.onLine === false) { resolve(); return; }
        next();
      }
      s.onload = function() {
        if (done) return;
        done = true;
        clearTimeout(timer);
        resolve();
      };
      s.onerror = fail;
      document.head.appendChild(s);
    }
    next();
  }

  function initMarkdown(){
    if(chatState.mdReady) return;
    if(typeof marked==='undefined'){
      // 5s 重试一次
      setTimeout(initMarkdown, 5000);
      return;
    }
    marked.setOptions({
      gfm:true,
      breaks:true,
      smartLists:true,
      smartypants:true
    });
    if(typeof hljs!=='undefined'){
      // marked v12 已移除 highlight 选项，必须用 renderer.code；
      // 旧写法静默失效（代码块永远无高亮）却仍加载 highlight.js
      var renderer=new marked.Renderer();
      renderer.code=function(code,infostring){
        var lang=String(infostring||'').trim().split(/\s+/)[0];
        var highlighted;
        try{
          highlighted=(lang&&hljs.getLanguage(lang))
            ? hljs.highlight(code,{language:lang}).value
            : hljs.highlightAuto(code).value;
        }catch(e){ highlighted=null; }
        if(highlighted===null){
          var esc=String(code).replace(/&/g,'&amp;').replace(/</g,'&lt;')
            .replace(/>/g,'&gt;');
          return '<pre><code>'+esc+'</code></pre>';
        }
        return '<pre><code class="hljs'+(lang?' language-'+lang:'')+'">'
          +highlighted+'</code></pre>';
      };
      if(typeof marked.use==='function'){
        marked.use({renderer:renderer});
      }else{
        marked.setOptions({renderer:renderer});
      }
    }
    chatState.mdReady=true;
    // 重新渲染已存在的对话（历史消息切换时用到）
    if(chatState.open) reRenderMessages();
  }

  /* ──── DOM 构建 ──── */
  function createWidget(){
    // button 而非 div：键盘可聚焦/回车触发，读屏能识别为按钮
    var fab=document.createElement('button');
    fab.type='button';
    fab.id='aiFab';
    fab.setAttribute('aria-label','打开 AI 学习助手');
    fab.setAttribute('aria-expanded','false');
    fab.setAttribute('aria-controls','aiChatPanel');
    fab.innerHTML=AI_ROBOT_SVG;
    fab.onclick=toggleChat;
    document.body.appendChild(fab);

    var panel=document.createElement('div');
    panel.id='aiChatPanel';
    panel.innerHTML=buildPanelHTML();
    document.body.appendChild(panel);

    var input=panel.querySelector('#aiInput');
    var sendBtn=panel.querySelector('#aiSendBtn');
    input.addEventListener('keydown',function(e){
      if(e.key==='Enter'&&!e.shiftKey){ e.preventDefault(); sendMessage(); }
    });
    sendBtn.addEventListener('click',sendMessage);

    panel.querySelector('#aiMinimizeBtn').addEventListener('click',function(){toggleChat();});
    panel.querySelector('#aiNewChat').addEventListener('click',newChat);
    panel.querySelector('#aiClearChat').addEventListener('click',clearChat);
    panel.querySelector('#aiContextToggle').addEventListener('click',toggleContext);
    panel.querySelector('#aiPageOnlyBtn').addEventListener('click',toggleStudentPageOnly);
    panel.querySelector('#aiSessionListBtn').addEventListener('click',toggleSessionList);
    var imageModeBtn=panel.querySelector('#aiImageModeBtn');
    if(imageModeBtn) imageModeBtn.addEventListener('click',toggleImageMode);
    var optimizePrompt=panel.querySelector('#aiOptimizePrompt');
    if(optimizePrompt) optimizePrompt.addEventListener('change',function(){
      chatState.optimizeImage=optimizePrompt.checked;
    });
    applyPageOnlyUI();
    bindSkillMenu(panel);

    var modelSel=panel.querySelector('#aiModelSelect');
    if(modelSel){
      modelSel.addEventListener('change',function(){
        chatState.selectedModel=modelSel.value;
        try{ localStorage.setItem('aiSelectedModel',modelSel.value); }catch(e){}
      });
    }

    if(chatState.configMode==='student' || chatState.canSelfConfig){
      var configBtn=panel.querySelector('#aiConfigBtn');
      if(configBtn){
        configBtn.style.display='';
        configBtn.href=chatState.canSelfConfig?'/teacher/ai_config':'/student/ai_config';
      }
    }
    if(chatState.imageEnabled){
      var imageBtn=panel.querySelector('#aiImageModeBtn');
      var optWrap=panel.querySelector('#aiOptimizeWrap');
      if(imageBtn) imageBtn.style.display='';
      if(optWrap) optWrap.style.display='none';
    }

    applyDeepseekControls(panel);
    var fileBtn=panel.querySelector('#aiFileBtn');
    if(fileBtn) fileBtn.addEventListener('click',function(){ panel.querySelector('#aiFileInput').click(); });
    var fileInput=panel.querySelector('#aiFileInput');
    if(fileInput) fileInput.addEventListener('change',function(){
      uploadDeepseekFiles(fileInput.files); fileInput.value='';
    });
    var micBtn=panel.querySelector('#aiMicBtn');
    if(micBtn) micBtn.addEventListener('click',startOrStopRecording);
    var audioInput=panel.querySelector('#aiAudioInput');
    if(audioInput) audioInput.addEventListener('change',function(){
      if(audioInput.files&&audioInput.files[0]) transcribeAudioFile(audioInput.files[0]);
      audioInput.value='';
    });
    var webBtn=panel.querySelector('#aiWebSearchBtn');
    if(webBtn) webBtn.addEventListener('click',function(){
      chatState.webSearch=!chatState.webSearch; renderDeepseekButtons();
    });
    var readBtn=panel.querySelector('#aiReadUrlBtn');
    if(readBtn) readBtn.addEventListener('click',function(){
      chatState.readUrl=!chatState.readUrl; renderDeepseekButtons();
    });
    var voiceSel=panel.querySelector('#aiVoiceSelect');
    if(voiceSel){
      voiceSel.value=chatState.voiceId;
      voiceSel.addEventListener('change',function(){
        if(voiceSel.value==='stella'||voiceSel.value==='tide'){
          chatState.voiceId=voiceSel.value;
          try{ localStorage.setItem('aiDeepseekVoice',chatState.voiceId); }catch(e){}
        }
      });
    }

    var overlay=panel.querySelector('#aiSessionOverlay');
    if(overlay) overlay.addEventListener('click',function(e){
      if(e.target===overlay) overlay.classList.remove('show');
    });
  }

  function buildPanelHTML(){
    return '<div class="ai-chat-header">'+
      '<div class="ai-chat-header-left">'+AI_ROBOT_SVG+'<span class="ai-chat-title">AI助手</span></div>'+
      '<div class="ai-chat-header-right">'+
        '<button id="aiSessionListBtn" class="ai-header-btn" title="历史会话"><span class="ai-symbol">⟲</span></button>'+
        '<button id="aiNewChat" class="ai-header-btn" title="新对话"><span class="ai-symbol">＋</span></button>'+
        '<button id="aiMinimizeBtn" class="ai-header-btn ai-minimize-btn" title="收起面板"><span class="ai-symbol">▾</span></button>'+
      '</div></div>'+
      '<div class="ai-chat-toolbar">'+
        '<div class="ai-skill-wrap" id="aiSkillWrap">'+
          '<button type="button" id="aiSkillBtn" class="ai-context-btn ai-skill-btn" aria-haspopup="true" aria-expanded="false" title="选择教学技能">'+
            '<span class="ai-skill-icon" aria-hidden="true">✦</span>'+
            '<span id="aiSkillLabel" class="ai-skill-label">技能：费曼简化</span>'+
            '<span class="ai-skill-caret" aria-hidden="true">▾</span>'+
          '</button>'+
          '<div id="aiSkillMenu" class="ai-skill-menu" role="menu" aria-label="选择教学技能"></div>'+
        '</div>'+
        '<button id="aiContextToggle" class="ai-context-btn ai-context-on" title="基于页面内容对话">'+
          '<span class="ai-context-label">基于页面内容</span></button>'+
        '<button id="aiPageOnlyBtn" class="ai-context-btn" title="限定学生的 AI 对话只围绕学生当前页面内容" style="display:none;">'+
          '<span class="ai-page-only-label">学生限本页：关</span></button>'+
        '<select id="aiModelSelect" class="ai-model-select" title="切换模型" style="display:none;"></select>'+
        '<button id="aiImageModeBtn" class="ai-context-btn" title="生成图片" style="display:none;">生图：关</button>'+
        '<button id="aiWebSearchBtn" class="ai-context-btn ai-ds-btn" title="允许模型联网搜索（DeepSeek 官方）" style="display:none;">联网：关</button>'+
        '<button id="aiReadUrlBtn" class="ai-context-btn ai-ds-btn ai-context-on" title="自动阅读消息中的链接（DeepSeek 官方）" style="display:none;">读链：开</button>'+
        '<select id="aiVoiceSelect" class="ai-model-select ai-ds-voice" title="朗读音色" style="display:none;">'+
          '<option value="stella">朗读：海星</option>'+
          '<option value="tide">朗读：暗潮</option>'+
        '</select>'+
        '<label id="aiOptimizeWrap" class="ai-optimize-wrap" style="display:none;">'+
          '<input type="checkbox" id="aiOptimizePrompt"> <span>先优化描述</span></label>'+
        '<button id="aiClearChat" class="ai-context-btn ai-clear-btn" title="清空当前对话"><span>清空对话</span></button>'+
        '<a id="aiConfigBtn" href="/student/ai_config" class="ai-context-btn ai-config-btn" title="AI配置" style="display:none;text-decoration:none;">'+
          '<span>配置</span></a>'+
      '</div>'+
      '<div id="aiMessages" class="ai-chat-messages"></div>'+
      '<div id="aiAttachBar" class="ai-attach-bar" style="display:none;"></div>'+
      '<div class="ai-chat-input-area">'+
        '<div class="ai-input-wrapper">'+
          '<button id="aiFileBtn" class="ai-input-tool" title="上传文件（DeepSeek 官方）" style="display:none;">文件</button>'+
          '<button id="aiMicBtn" class="ai-input-tool" title="语音输入（DeepSeek 官方）" style="display:none;">语音</button>'+
          '<textarea id="aiInput" class="ai-input" placeholder="输入消息..." rows="1"></textarea>'+
          '<button id="aiSendBtn" class="ai-send-btn" title="发送"><span class="ai-send-symbol">➤</span></button>'+
        '</div>'+
        '<input type="file" id="aiFileInput" multiple style="display:none" '+
          'accept=".pdf,.doc,.docx,.ppt,.pptx,.png,.jpg,.jpeg,.webp,.gif,.bmp,.tif,.tiff,.txt,.md,.csv,.json,.xlsx,.xls,.epub,.mobi">'+
        '<input type="file" id="aiAudioInput" style="display:none" '+
          'accept=".wav,.ogg,.opus,audio/wav,audio/ogg,audio/opus">'+
      '</div></div>'+
      '<div id="aiSessionOverlay" class="ai-session-overlay">'+
        '<div class="ai-session-drawer">'+
          '<div class="ai-session-drawer-header"><span>历史会话</span>'+
            '<button class="ai-header-btn" onclick="document.getElementById(\'aiSessionOverlay\').classList.remove(\'show\')"><span class="ai-symbol">×</span></button></div>'+
          '<div id="aiSessionList" class="ai-session-list"></div>'+
        '</div></div>';
  }

  /* ──── 面板控制 ──── */
  function toggleChat(){
    var panel=document.getElementById('aiChatPanel');
    var fab=document.getElementById('aiFab');
    chatState.open=!chatState.open;
    if(chatState.open){
      // 首次打开才下载 marked/highlight（约 157KB）：AI 关闭或从不使用
      // 的页面不再为未用到的渲染器付出流量
      loadMarkdownEngine();
      panel.classList.add('show'); fab.classList.add('hide');
      fab.setAttribute('aria-expanded','true');
      fab.setAttribute('aria-label','收起 AI 学习助手');
      if(!chatState.sessionId) showWelcome();
      document.getElementById('aiInput').focus();
    }else{
      panel.classList.remove('show'); fab.classList.remove('hide');
      fab.setAttribute('aria-expanded','false');
      fab.setAttribute('aria-label','打开 AI 学习助手');
    }
  }

  function showWelcome(){
    var msgDiv=document.getElementById('aiMessages');
    var needConfig=(chatState.configMode==='student'&&!chatState.studentConfigured)||
      (chatState.isTeacherEdit&&!chatState.teacherConfigured&&chatState.configMode==='teacher');
    if(needConfig){
      var teacherNeed=chatState.isTeacherEdit;
      msgDiv.innerHTML='<div class="ai-welcome">'+
        '<div class="ai-welcome-icon">'+AI_ROBOT_SVG+'</div>'+
        '<div class="ai-welcome-text">你好！我是AI学习助手</div>'+
        '<div class="ai-welcome-sub" style="color:#e67e22;">'+
          (teacherNeed?'尚未配置教师 AI API，请先完成配置（只读模式会自动使用管理员配置）':'当前为「学生端自行配置」模式，请先配置API信息')+
        '</div>'+
        '<div style="margin-top:12px;"><a href="'+(teacherNeed?'/teacher/ai_config':'/student/ai_config')+'" class="btn btn-warning btn-sm" style="color:#333;text-decoration:none;">前往配置</a></div>'+
      '</div>'; return;
    }
    msgDiv.innerHTML='<div class="ai-welcome">'+
      '<div class="ai-welcome-icon">'+AI_ROBOT_SVG+'</div>'+
      '<div class="ai-welcome-text">你好！我是AI学习助手</div>'+
      '<div class="ai-welcome-sub">'+(chatState.pageOnly?'老师已限定：我只围绕你当前页面的内容回答问题':(chatState.usePageContext?'当前已开启页面内容感知，我可以基于当前页面内容回答你的问题':'当前为自由对话模式'))+'</div>'+
      (chatState.skillsMeta.length?'<div class="ai-welcome-skill">讲解技能：'+
        (skillNames().length?escapeHtml(skillNames().join('、')):'不使用技能')+
        '<span>可在上方「技能」中切换</span></div>':'')+
      '<div class="ai-welcome-hints">'+
        '<button type="button" class="ai-hint" onclick="document.getElementById(\'aiInput\').value=\'帮我解释一下这个页面的内容\';document.getElementById(\'aiInput\').focus();">💡 解释页面内容</button>'+
        '<button type="button" class="ai-hint" onclick="document.getElementById(\'aiInput\').value=\'这个知识点我不太理解，请详细说明\';document.getElementById(\'aiInput\').focus();">📖 详细说明知识点</button>'+
        '<button type="button" class="ai-hint" onclick="document.getElementById(\'aiInput\').value=\'请给我出几道相关的练习题\';document.getElementById(\'aiInput\').focus();">✏️ 出练习题</button>'+
      '</div></div>';
  }

  function toggleContext(){
    if(chatState.pageOnly) return;   // 教师已限定：学生不能切回自由对话
    chatState.usePageContext=!chatState.usePageContext;
    renderContextButton();
  }

  function renderContextButton(){
    var btn=document.getElementById('aiContextToggle');
    if(!btn) return;
    var label=btn.querySelector('.ai-context-label');
    if(chatState.usePageContext){
      btn.classList.add('ai-context-on'); btn.classList.remove('ai-context-off');
      label.textContent=chatState.pageOnly?'仅限本页内容':'基于页面内容';
    }else{
      btn.classList.remove('ai-context-on'); btn.classList.add('ai-context-off');
      label.textContent='自由对话';
    }
    btn.disabled=chatState.pageOnly;
    btn.title=chatState.pageOnly?'老师已限定：AI 只围绕你当前页面的内容回答':'基于页面内容对话';
  }

  // 学生端：服务端回传 page_only 时同步状态（教师可能在课中随时开关）
  function setPageOnly(on){
    if(chatState.canControlPageOnly) return;   // 教师/管理员自身不受限
    chatState.pageOnly=!!on;
    if(chatState.pageOnly) chatState.usePageContext=true;
    renderContextButton();
    applyDeepseekControls();
  }

  function applyPageOnlyUI(){
    renderContextButton();
    var btn=document.getElementById('aiPageOnlyBtn');
    if(!btn) return;
    btn.style.display=chatState.canControlPageOnly?'':'none';
    btn.querySelector('.ai-page-only-label').textContent=
      '学生限本页：'+(chatState.studentPageOnly?'开':'关');
    btn.classList.toggle('ai-context-on',chatState.studentPageOnly);
  }

  function toggleStudentPageOnly(){
    var next=!chatState.studentPageOnly;
    fetch('/teacher/ai/page-only',{method:'POST',headers:jsonHeaders(),
      body:JSON.stringify({enabled:next})})
      .then(function(r){ return r.json(); })
      .then(function(d){
        if(!d.success){ alert(d.msg||d.message||'切换失败'); return; }
        chatState.studentPageOnly=!!d.enabled;
        applyPageOnlyUI();
      })
      .catch(function(){ alert('网络错误，切换失败'); });
  }

  /* ──── DeepSeek 全家桶入口（联网/读链/文件/语音） ──── */
  function applyDeepseekControls(panel){
    panel=panel||document.getElementById('aiChatPanel');
    if(!panel) return;
    var show=!!chatState.deepseekTools;
    ['#aiWebSearchBtn','#aiReadUrlBtn','#aiVoiceSelect','#aiFileBtn','#aiMicBtn']
      .forEach(function(sel){
        var el=panel.querySelector(sel);
        if(el) el.style.display=show?'':'none';
      });
    if(show&&chatState.pageOnly){
      // 教师限定本页内容时，联网/读链/文件会绕过内容边界，隐藏入口。
      ['#aiWebSearchBtn','#aiReadUrlBtn','#aiFileBtn'].forEach(function(sel){
        var el=panel.querySelector(sel); if(el) el.style.display='none';
      });
    }
    renderDeepseekButtons();
  }

  function renderDeepseekButtons(){
    var web=document.getElementById('aiWebSearchBtn');
    if(web){
      web.textContent='联网：'+(chatState.webSearch?'开':'关');
      web.classList.toggle('ai-context-on',chatState.webSearch);
      web.classList.toggle('ai-context-off',!chatState.webSearch);
    }
    var read=document.getElementById('aiReadUrlBtn');
    if(read){
      read.textContent='读链：'+(chatState.readUrl?'开':'关');
      read.classList.toggle('ai-context-on',chatState.readUrl);
      read.classList.toggle('ai-context-off',!chatState.readUrl);
    }
  }

  function renderAttachBar(){
    var bar=document.getElementById('aiAttachBar');
    if(!bar) return;
    bar.innerHTML='';
    if(!chatState.files.length){ bar.style.display='none'; return; }
    bar.style.display='flex';
    chatState.files.forEach(function(file,idx){
      var chip=document.createElement('span');
      chip.className='ai-attach-chip'+(file.uploading?' ai-attach-uploading':'');
      var name=document.createElement('span');
      name.className='ai-attach-name';
      name.textContent=file.name||'文件';
      chip.appendChild(name);
      var state=document.createElement('span');
      state.className='ai-attach-state';
      state.textContent=file.uploading?'上传中…':
        (file.purpose==='user_data'?'文本':'图文解析');
      chip.appendChild(state);
      var rm=document.createElement('button');
      rm.type='button'; rm.className='ai-attach-remove'; rm.title='移除';
      rm.setAttribute('aria-label','移除文件 '+file.name);
      rm.textContent='×';
      rm.addEventListener('click',function(){
        chatState.files.splice(idx,1); renderAttachBar();
      });
      chip.appendChild(rm);
      bar.appendChild(chip);
    });
  }

  function uploadDeepseekFiles(fileList){
    if(!fileList||!fileList.length) return;
    Array.prototype.forEach.call(fileList,function(file){
      if(file.size>100*1024*1024){ alert(file.name+' 超过 100MB，无法上传'); return; }
      var temp={id:'',name:file.name,purpose:'',uploading:true};
      chatState.files.push(temp);
      chatState.uploading++;
      renderAttachBar();
      var fd=new FormData();
      fd.append('file',file);
      var headers={};
      var token=getCsrfToken();
      if(token) headers['X-CSRFToken']=token;
      fetch('/api/ai/deepseek/files',{method:'POST',headers:headers,body:fd,credentials:'same-origin'})
        .then(function(response){
          return response.json().catch(function(){return {};}).then(function(j){
            if(!response.ok||!j.success) throw new Error(j.message||('文件上传失败（HTTP '+response.status+'）'));
            return j;
          });
        })
        .then(function(j){
          var pos=chatState.files.indexOf(temp);
          if(pos>=0&&j.file){
            chatState.files[pos]={id:j.file.id,name:j.file.name||file.name,
              purpose:j.file.purpose||'',uploading:false};
          }
        })
        .catch(function(e){
          var pos=chatState.files.indexOf(temp);
          if(pos>=0) chatState.files.splice(pos,1);
          alert((e&&e.message)||'文件上传失败');
        })
        .then(function(){
          chatState.uploading=Math.max(0,chatState.uploading-1);
          renderAttachBar();
        });
    });
  }

  function appendToInput(text){
    var input=document.getElementById('aiInput');
    if(!input||!text) return;
    var value=input.value||'';
    if(value&&!/\s$/.test(value)) value+=' ';
    input.value=value+text;
    autoResizeInput();
    input.focus();
  }

  function transcribeAudioFile(file){
    if(!file) return;
    if(file.size>8*1024*1024){ alert('音频不能超过 8MB（最长 120 秒）'); return; }
    transcribeAudioBlob(file,file.name||'speech.wav');
  }

  function transcribeAudioBlob(blob,filename){
    var btn=document.getElementById('aiMicBtn');
    if(btn){ btn.disabled=true; btn.textContent='识别中'; }
    var fd=new FormData();
    fd.append('file',blob,filename||'speech.wav');
    var headers={};
    var token=getCsrfToken();
    if(token) headers['X-CSRFToken']=token;
    function done(){ if(btn){ btn.disabled=false; } setMicRecording(false); }
    fetch('/api/ai/deepseek/asr',{method:'POST',headers:headers,body:fd,credentials:'same-origin'})
      .then(function(response){
        return response.json().catch(function(){return {};}).then(function(j){
          if(!response.ok||!j.success) throw new Error(j.message||('语音识别失败（HTTP '+response.status+'）'));
          return j;
        });
      })
      .then(function(j){ appendToInput(j.text||''); done(); })
      .catch(function(e){ done(); alert((e&&e.message)||'语音识别失败'); });
  }

  function setMicRecording(on){
    var btn=document.getElementById('aiMicBtn');
    if(!btn) return;
    btn.textContent=on?'停止':'语音';
    btn.classList.toggle('ai-mic-recording',!!on);
    btn.title=on?'点击停止录音':'语音输入（DeepSeek 官方）';
  }

  function downsampleBuffer(buffer,fromRate,toRate){
    if(!buffer.length||!fromRate||fromRate<=toRate) return buffer;
    var ratio=fromRate/toRate;
    var length=Math.max(1,Math.round(buffer.length/ratio));
    var out=new Float32Array(length);
    var offset=0;
    for(var i=0;i<length;i++){
      var next=Math.round((i+1)*ratio);
      var sum=0,count=0;
      for(var j=offset;j<next&&j<buffer.length;j++){ sum+=buffer[j]; count++; }
      out[i]=count?sum/count:0;
      offset=next;
    }
    return out;
  }

  function encodeWav(samples,sampleRate){
    var buffer=new ArrayBuffer(44+samples.length*2);
    var view=new DataView(buffer);
    function writeStr(offset,str){
      for(var i=0;i<str.length;i++) view.setUint8(offset+i,str.charCodeAt(i));
    }
    writeStr(0,'RIFF'); view.setUint32(4,36+samples.length*2,true);
    writeStr(8,'WAVE'); writeStr(12,'fmt ');
    view.setUint32(16,16,true); view.setUint16(20,1,true);
    view.setUint16(22,1,true); view.setUint32(24,sampleRate,true);
    view.setUint32(28,sampleRate*2,true); view.setUint16(32,2,true);
    view.setUint16(34,16,true); writeStr(36,'data');
    view.setUint32(40,samples.length*2,true);
    var offset=44;
    for(var i=0;i<samples.length;i++){
      var s=Math.max(-1,Math.min(1,samples[i]));
      view.setInt16(offset,s<0?s*0x8000:s*0x7FFF,true);
      offset+=2;
    }
    return new Blob([view],{type:'audio/wav'});
  }

  function stopRecording(){
    var rec=chatState.recording;
    if(!rec) return;
    chatState.recording=null;
    setMicRecording(false);
    if(rec.timer) clearInterval(rec.timer);
    var sampleRate=rec.sampleRate;
    try{ rec.source.disconnect(); rec.processor.disconnect(); }catch(e){}
    try{ rec.ctx.close(); }catch(e){}
    try{ rec.stream.getTracks().forEach(function(t){ t.stop(); }); }catch(e){}
    var total=0;
    rec.chunks.forEach(function(c){ total+=c.length; });
    if(!total){ alert('没有录到声音，请重试'); return; }
    var merged=new Float32Array(total), offset=0;
    rec.chunks.forEach(function(c){ merged.set(c,offset); offset+=c.length; });
    var samples=downsampleBuffer(merged,sampleRate||16000,16000);
    transcribeAudioBlob(encodeWav(samples,16000),'speech.wav');
  }

  function startOrStopRecording(){
    if(chatState.recording){ stopRecording(); return; }
    if(!navigator.mediaDevices||!navigator.mediaDevices.getUserMedia||
       !(window.AudioContext||window.webkitAudioContext)){
      alert('当前页面无法录音（浏览器要求 HTTPS 或 localhost）。请改用上传音频文件。');
      var audioInput=document.getElementById('aiAudioInput');
      if(audioInput) audioInput.click();
      return;
    }
    navigator.mediaDevices.getUserMedia({audio:true}).then(function(stream){
      var Ctx=window.AudioContext||window.webkitAudioContext;
      var ctx=new Ctx();
      var source=ctx.createMediaStreamSource(stream);
      var processor=ctx.createScriptProcessor(4096,1,1);
      var mute=ctx.createGain();
      mute.gain.value=0;
      var rec={stream:stream,ctx:ctx,source:source,processor:processor,
               chunks:[],sampleRate:ctx.sampleRate,startedAt:Date.now(),timer:null};
      chatState.recording=rec;
      setMicRecording(true);
      processor.onaudioprocess=function(e){
        if(chatState.recording!==rec) return;
        rec.chunks.push(new Float32Array(e.inputBuffer.getChannelData(0)));
        if(Date.now()-rec.startedAt>120000) stopRecording();
      };
      rec.timer=setInterval(function(){
        if(chatState.recording===rec&&Date.now()-rec.startedAt>120000) stopRecording();
      },1000);
      source.connect(processor);
      processor.connect(mute);
      mute.connect(ctx.destination);
    }).catch(function(err){
      var msg=(err&&err.name==='NotAllowedError')?'麦克风权限被拒绝':
        '无法使用麦克风'+(err&&err.message?'（'+err.message+'）':'');
      alert(msg+'。可改用上传音频文件。');
      var audioInput=document.getElementById('aiAudioInput');
      if(audioInput) audioInput.click();
    });
  }

  function stopTts(){
    if(chatState.ttsAudio){
      try{ chatState.ttsAudio.pause(); }catch(e){}
      chatState.ttsAudio=null;
    }
    if(chatState.ttsUrl){
      try{ URL.revokeObjectURL(chatState.ttsUrl); }catch(e){}
      chatState.ttsUrl='';
    }
    document.querySelectorAll('.ai-action-btn[data-action="speak"]').forEach(function(btn){
      btn.classList.remove('ai-speaking');
      var sp=btn.querySelector('span');
      if(sp) sp.textContent='朗读';
    });
  }

  function speakMessage(bubble){
    var btn=bubble.querySelector('.ai-action-btn[data-action="speak"]');
    if(btn&&btn.classList.contains('ai-speaking')){ stopTts(); return; }
    var text=messagePlainText(bubble);
    if(!text) return;
    stopTts();
    fetch('/api/ai/deepseek/tts',{
      method:'POST',headers:jsonHeaders(),
      body:JSON.stringify({text:text,voice_id:chatState.voiceId})
    }).then(function(response){
      if(!response.ok){
        return response.json().catch(function(){return {};}).then(function(j){
          throw new Error(j.message||('朗读失败（HTTP '+response.status+'）'));
        });
      }
      return response.blob();
    }).then(function(blob){
      var url=URL.createObjectURL(blob);
      chatState.ttsUrl=url;
      var audio=new Audio(url);
      chatState.ttsAudio=audio;
      if(btn){
        btn.classList.add('ai-speaking');
        var sp=btn.querySelector('span');
        if(sp) sp.textContent='停止';
      }
      audio.onended=audio.onerror=function(){ stopTts(); };
      audio.play().catch(function(e){
        stopTts();
        alert('无法播放朗读音频'+(e&&e.message?'：'+e.message:''));
      });
    }).catch(function(e){
      stopTts();
      alert((e&&e.message)||'朗读失败');
    });
  }

  function setToolStatus(bubble,text){
    var wrap=bubble.querySelector('.ai-msg-bubble-wrap');
    if(!wrap) return;
    var el=wrap.querySelector('.ai-tool-status');
    if(!el){
      el=document.createElement('div');
      el.className='ai-tool-status';
      var actions=wrap.querySelector('.ai-msg-actions');
      wrap.insertBefore(el,actions||null);
    }
    el.textContent=text||'';
    el.style.display=text?'inline-flex':'none';
  }

  function renderSources(bubble,sources){
    if(!bubble||!sources||!sources.length) return;
    var wrap=bubble.querySelector('.ai-msg-bubble-wrap');
    if(!wrap) return;
    var old=wrap.querySelector('.ai-sources');
    if(old) old.remove();
    var box=document.createElement('div');
    box.className='ai-sources';
    var title=document.createElement('div');
    title.className='ai-sources-title';
    title.textContent='参考来源';
    box.appendChild(title);
    var count=0;
    sources.forEach(function(src){
      if(!src||typeof src.url!=='string'||!/^https?:\/\//i.test(src.url)) return;
      var a=document.createElement('a');
      a.className='ai-source-link';
      a.href=src.url;
      a.target='_blank';
      a.rel='noopener noreferrer';
      a.textContent=src.title||src.url;
      box.appendChild(a);
      count++;
    });
    if(count) wrap.appendChild(box);
  }

  /* ──── 工具函数 ──── */
  // 课件嵌在 iframe 里：独立资源页 #mainFrame/#resourceFrame，课堂页按当前
  // 展示的 #docFrame/#linkFrame/#pptistFrame（此前课堂页只取到外壳文字）
  var CONTENT_FRAMES=['#mainFrame','#resourceFrame','#docFrame','#linkFrame','#pptistFrame'];
  function getPageContent(){
    var content='';
    for(var i=0;i<CONTENT_FRAMES.length&&!content;i++){
      var f=document.querySelector(CONTENT_FRAMES[i]);
      if(!f||f.classList.contains('hidden')||f.offsetParent===null) continue;
      try{ content=(f.contentDocument&&f.contentDocument.body)?f.contentDocument.body.innerText:''; }
      catch(e){ content=''; }   // 跨源课件读不到，回退主页面文字
    }
    if(!content){
      var main=document.querySelector('main')||document.querySelector('.container')||document.body;
      content=main.innerText||'';
    }
    return content.trim().substring(0,3000);
  }

  function getPageImages(){
    var out=[], seen={};
    function scan(doc){
      if(!doc||out.length>=3) return;
      var imgs;
      try{ imgs=doc.querySelectorAll('img'); }catch(e){ return; }
      for(var i=0;i<imgs.length&&out.length<3;i++){
        var el=imgs[i];
        try{
          if(el.closest&&el.closest('#aiChatPanel,.navbar,.lesson-topbar,.lesson-toolbar,.toolbar,.admin-bar,.ai-msg,.modal-header')) continue;
          if(!el.complete||!el.naturalWidth||!el.naturalHeight) continue;
          if(el.naturalWidth<80||el.naturalHeight<80) continue;
          var src=el.currentSrc||el.src||'';
          if(!src||seen[src]) continue;
          seen[src]=true;
          var scale=Math.min(1,1024/Math.max(el.naturalWidth,el.naturalHeight));
          var c=document.createElement('canvas');
          c.width=Math.max(1,Math.round(el.naturalWidth*scale));
          c.height=Math.max(1,Math.round(el.naturalHeight*scale));
          var cx=c.getContext('2d');
          cx.fillStyle='#fff'; cx.fillRect(0,0,c.width,c.height);
          cx.drawImage(el,0,0,c.width,c.height);
          var data=c.toDataURL('image/jpeg',0.82);
          if(data.length>1500000) continue;   // 单张约 1.1MB 上限
          out.push(data);
        }catch(e){ /* 跨源图片会污染 canvas，跳过 */ }
      }
    }
    scan(document);
    for(var i=0;i<CONTENT_FRAMES.length;i++){
      try{
        var f=document.querySelector(CONTENT_FRAMES[i]);
        if(f&&!f.classList.contains('hidden')&&f.offsetParent!==null){
          scan(f.contentDocument);
        }
      }catch(e){ /* sandbox/跨源 */ }
    }
    return out;
  }

  function showVisionNotice(){
    var msgDiv=document.getElementById('aiMessages');
    if(!msgDiv) return;
    var el=document.createElement('div');
    el.className='ai-vision-notice';
    el.textContent='当前模型未开启图片理解，页面图片内容不会发送。';
    msgDiv.appendChild(el);
    msgDiv.scrollTop=msgDiv.scrollHeight;
  }

  function escapeHtml(str){
    var div=document.createElement('div');
    div.textContent=str;
    return div.innerHTML.replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  function getCsrfToken(){
    if(window.getCsrfToken) return window.getCsrfToken();
    var parts=document.cookie?document.cookie.split(';'):[];
    for(var i=0;i<parts.length;i++){
      var part=parts[i].trim();
      if(part.indexOf('csrf_token=')===0) return decodeURIComponent(part.substring('csrf_token='.length));
    }
    return '';
  }

  function jsonHeaders(){
    var headers={'Content-Type':'application/json'};
    var token=getCsrfToken();
    if(token) headers['X-CSRFToken']=token;
    return headers;
  }

  // 非 2xx：取后端 JSON 里的 msg/message 给用户看（429 限流、503 维护等），
  // 此前一律显示"网络错误"，用户无从判断该等待还是改写提问
  function httpError(response){
    return response.json().catch(function(){ return {}; }).then(function(j){
      if(j&&j.page_only) setPageOnly(true);
      var e=new Error('HTTP '+response.status);
      e.userMessage=(j&&(j.msg||j.message))||('请求失败（HTTP '+response.status+'）');
      throw e;
    });
  }

  // AI 输出 HTML 消毒：使用 DOMPurify（成熟白名单库）替代原自研遍历器，
  // 覆盖 srcset/style 等自研实现遗漏的属性向量。钩子在模块初始化时注册一次。
  if (window.DOMPurify) {
    DOMPurify.addHook('afterSanitizeAttributes', function (node) {
      if (node.tagName === 'A') {
        node.setAttribute('rel', 'noopener noreferrer');
        if (!node.getAttribute('target')) node.setAttribute('target', '_blank');
      }
      if (node.tagName === 'CODE' && node.getAttribute('class') &&
          !/^language-[a-z0-9_-]+$/i.test(node.getAttribute('class'))) {
        node.removeAttribute('class');
      }
    });
  }

  function sanitizeRenderedHtml(html){
    if (!window.DOMPurify) {
      // fail-closed：净化库缺失时不再透传原始 HTML，降级为纯文本转义
      if (window.console && console.warn) console.warn('[ai-chat] DOMPurify 未加载，已降级为纯文本渲染');
      return escapeHtml(html);
    }
    return DOMPurify.sanitize(html, {
      ALLOWED_TAGS: [
        'a','p','br','strong','em','b','i','u','s',
        'ul','ol','li','blockquote','pre','code',
        'table','thead','tbody','tr','th','td',
        'h1','h2','h3','h4','h5','h6','hr','img'
      ],
      ALLOWED_ATTR: ['href','title','target','rel','class','colspan','rowspan',
                     'src','alt'],
      // 协议白名单：仅 http/https/mailto/锚点/相对路径
      ALLOWED_URI_REGEXP: /^(?:https?|mailto|#|\/)/i,
      FORBID_TAGS: ['style','iframe','object','embed','form','input','button',
                    'script','svg','math','video','audio','link','meta'],
      KEEP_CONTENT: true
    });
  }

  /* ──── Markdown 渲染 ──── */
  function renderMarkdown(text){
    if(!chatState.mdReady||typeof marked==='undefined'){
      return escapeHtml(text).replace(/\n/g,'<br>');
    }
    try{
      var html=marked.parse(text);
      html=html.replace(/<script\b[^<]*(?:(?!<\/script>)<[^<]*)*<\/script>/gi,'');
      return sanitizeRenderedHtml(html);
    }catch(e){
      return escapeHtml(text).replace(/\n/g,'<br>');
    }
  }

  /* ──── 消息渲染 ──── */
  function addMessage(role,text,opts){
    opts=opts||{};
    var msgDiv=document.getElementById('aiMessages');
    var welcome=msgDiv.querySelector('.ai-welcome');
    if(welcome) welcome.remove();

    var bubble=document.createElement('div');
    bubble.className='ai-msg ai-msg-'+role;
    bubble.setAttribute('data-role',role);

    var displayText;
    if(role==='assistant'){
      displayText=renderMarkdown(text);
    }else{
      displayText=escapeHtml(text).replace(/\n/g,'<br>');
    }

    var actionsHTML='<div class="ai-msg-actions">';
    if(role==='user'){
      actionsHTML+='<button class="ai-action-btn" data-action="resend" title="重新提问"><span>重新提问</span></button>'+
        '<button class="ai-action-btn" data-action="copy" title="复制"><span>复制</span></button>';
    }else{
      actionsHTML+='<button class="ai-action-btn" data-action="copy" title="复制"><span>复制</span></button>'+
        '<button class="ai-action-btn" data-action="regenerate" title="重新生成"><span>重新生成</span></button>';
      if(chatState.deepseekTools){
        actionsHTML+='<button class="ai-action-btn" data-action="speak" title="朗读回答"><span>朗读</span></button>';
      }
    }
    actionsHTML+='</div>';

    bubble.innerHTML='<div class="ai-msg-avatar"><span>'+(role==='user'?'我':'AI')+'</span></div>'+
      '<div class="ai-msg-bubble-wrap">'+
        '<div class="ai-msg-bubble ai-msg-bubble-'+role+'"><div class="ai-msg-text">'+displayText+'</div></div>'+
        actionsHTML+'</div>';

    if(opts.streaming) bubble.classList.add('ai-msg-streaming');

    bindActions(bubble,text);
    msgDiv.appendChild(bubble);
    msgDiv.scrollTop=msgDiv.scrollHeight;
    return bubble;
  }

  function bindActions(bubble,text){
    bubble.querySelectorAll('.ai-action-btn').forEach(function(btn){
      btn.addEventListener('click',function(){
        var action=btn.getAttribute('data-action');
        if(action==='resend') resendMessage(text);
        // 流式回复的消息在创建时 text 为空、内容随后写入 DOM；
        // 不能捕获创建时的 text，否则复制到空内容/剪贴板残留旧值
        // （用户看到的就是复制到了此前复制的 API Key）。
        else if(action==='copy') copyToClipboard(messagePlainText(bubble));
        else if(action==='regenerate') regenerateLastResponse();
        else if(action==='speak') speakMessage(bubble);
      });
    });
  }

  function messagePlainText(bubble){
    var el=bubble.querySelector('.ai-msg-text');
    if(!el) return '';
    var value=el.innerText!==undefined?el.innerText:el.textContent;
    return String(value||'').trim();
  }

  /* ──── SSE 流式发送 ──── */
  function sendMessage(){
    if(chatState.imageMode){ sendImageMessage(); return; }
    var input=document.getElementById('aiInput');
    var text=input.value.trim();
    if(chatState.sending) return;
    if(chatState.uploading>0){ alert('文件仍在上传，请稍候再发送'); return; }
    if(!text&&!chatState.files.length) return;
    if(!text) text='请阅读这些文件并总结要点。';

    if(chatState.configMode==='student'&&!chatState.studentConfigured){ showWelcome(); return; }

    chatState.lastUserMessage=text;
    chatState.lastRequestImage=false;
    chatState.sending=true;
    input.value=''; autoResizeInput();

    var outgoingFiles=chatState.files.filter(function(f){
      return f.id&&!f.uploading;
    }).map(function(f){
      return {id:f.id,name:f.name,purpose:f.purpose};
    });
    var userBubble=addMessage('user',text);
    if(outgoingFiles.length){
      var bar=document.createElement('div');
      bar.className='ai-user-attachments';
      outgoingFiles.forEach(function(f){
        var chip=document.createElement('span');
        chip.className='ai-user-attach';
        chip.textContent=f.name||'文件';
        bar.appendChild(chip);
      });
      userBubble.querySelector('.ai-msg-bubble').appendChild(bar);
    }
    chatState.files=[];
    renderAttachBar();

    // 页面内容始终随请求发送：教师可能在课中随时开启"仅限本页"，服务端据此
    // 强制页面上下文；未开启时服务端按 use_page_context 决定是否使用
    var pageContent=getPageContent();
    var pageImages=(chatState.usePageContext||chatState.pageOnly)?getPageImages():[];
    if(pageImages.length&&!chatState.visionEnabled){
      showVisionNotice();
      pageImages=[];
    }
    chatState.lastImages=pageImages;

    var streamBubble=addMessage('assistant','',{streaming:true});
    var streamEl=streamBubble.querySelector('.ai-msg-text');
    var fullContent='';
    var renderTimer=null;
    var finished=false;
    var refused=false;
    var refusalText='';
    var sourcesList=[];

    function throttledRender(){
      if(renderTimer) return;
      renderTimer=setTimeout(function(){
        renderTimer=null;
        streamEl.innerHTML=renderMarkdown(fullContent);
        var msgDiv=document.getElementById('aiMessages');
        msgDiv.scrollTop=msgDiv.scrollHeight;
      },50);
    }

    fetch('/api/ai/chat/stream',{
      method:'POST',
      headers:jsonHeaders(),
      body:JSON.stringify({
        message:text,
        session_id:chatState.sessionId,
        page_content:pageContent,
        images:pageImages,
        use_page_context:chatState.usePageContext,
        model:chatState.selectedModel||'',
        skills:chatState.skills||[],
        deepseek:{web_search:chatState.webSearch,read_url:chatState.readUrl},
        files:outgoingFiles
      })
    }).then(function(response){
      if(!response.ok) return httpError(response);
      var reader=response.body.getReader();
      var decoder=new TextDecoder();
      var buffer='';

      function processChunk(){
        return reader.read().then(function(result){
          if(result.done){
            // 流结束却没收到 done/error（断连、代理截断）：就地收尾，
            // 否则 sending 恒为 true，之后发送在入口被静默拦截直到刷新页面
            if(!finished){
              finished=true;
              if(renderTimer){ clearTimeout(renderTimer); renderTimer=null; }
              streamEl.innerHTML=refused?escapeHtml(refusalText||'内容未通过安全审核，请调整问题后重试'):renderMarkdown(fullContent||'⚠️ 回复中断，请重试');
              streamBubble.classList.remove('ai-msg-streaming');
              streamBubble.removeAttribute('id');
              chatState.sending=false;
            }
            return;
          }
          buffer+=decoder.decode(result.value,{stream:true});
          var lines=buffer.split('\n');
          buffer=lines.pop()||'';

          for(var i=0;i<lines.length;i++){
            var line=lines[i].trim();
            if(line.indexOf('data: ')!==0) continue;

            var data;
            try{ data=JSON.parse(line.substring(6)); }catch(e){ continue; }

            if(data.status){
              streamEl.textContent=data.status;
              continue;
            }
            if(data.tool_event){
              setToolStatus(streamBubble,data.tool_event.label||'正在联网…');
              continue;
            }
            if(data.sources){
              sourcesList=data.sources||[];
              continue;
            }
            if(data.refusal){
              // 已流式展示的部分必须撤回：内容审核拒答时整段回答无效
              refused=true;
              refusalText=data.message||'内容未通过安全审核，请调整问题后重试';
              if(renderTimer){ clearTimeout(renderTimer); renderTimer=null; }
              fullContent='';
              streamEl.textContent=refusalText;
              setToolStatus(streamBubble,'');
              continue;
            }
            if(data.error){
              // 出错时后端不再发送 done 事件——必须就地复位会话状态，
              // 否则 sending 恒为 true，后续发送在入口被静默拦截
              finished=true;
              if(renderTimer){ clearTimeout(renderTimer); renderTimer=null; }
              streamEl.textContent='⚠️ '+data.error;
              streamBubble.classList.remove('ai-msg-streaming');
              streamBubble.removeAttribute('id');
              chatState.sending=false;
              break;
            }
            if(data.done){
              finished=true;
              // 清除节流 timer，最终渲染
              if(renderTimer){ clearTimeout(renderTimer); renderTimer=null; }
              if(refused){
                streamEl.textContent=refusalText||'内容未通过安全审核，请调整问题后重试';
              }else{
                streamEl.innerHTML=renderMarkdown(fullContent);
                renderSources(streamBubble,sourcesList);
              }
              setToolStatus(streamBubble,'');
              streamBubble.classList.remove('ai-msg-streaming');
              streamBubble.removeAttribute('id');

              if(data.session_id) chatState.sessionId=data.session_id;
              if(data.page_only!==undefined) setPageOnly(data.page_only);

              // 截断续写按钮
              if(data.truncated){
                var contBtn=document.createElement('button');
                contBtn.className='ai-continue-btn';
                contBtn.textContent='▸ 继续生成';
                contBtn.addEventListener('click',function(){
                  contBtn.remove();
                  sendContinueMessage();
                });
                streamBubble.querySelector('.ai-msg-bubble-wrap').appendChild(contBtn);
              }
              chatState.sending=false;
              return;
            }
            if(data.content){
              fullContent+=data.content;
              throttledRender();
            }
          }
          return processChunk();
        });
      }
      return processChunk();
    }).catch(function(e){
      if(renderTimer){ clearTimeout(renderTimer); renderTimer=null; }
      streamBubble.classList.remove('ai-msg-streaming');
      streamEl.textContent='⚠️ '+((e&&e.userMessage)||'网络错误，请稍后重试');
      chatState.sending=false;
    });
  }

  function sendContinueMessage(){
    if(chatState.sending) return;
    chatState.sending=true;

    var streamBubble=addMessage('assistant','',{streaming:true});
    var streamEl=streamBubble.querySelector('.ai-msg-text');
    var fullContent='';
    var renderTimer=null;
    var finished=false;
    var refused=false;
    var refusalText='';
    var sourcesList=[];

    function throttledRender(){
      if(renderTimer) return;
      renderTimer=setTimeout(function(){
        renderTimer=null;
        streamEl.innerHTML=renderMarkdown(fullContent);
        var msgDiv=document.getElementById('aiMessages');
        msgDiv.scrollTop=msgDiv.scrollHeight;
      },50);
    }

    var pageContent=getPageContent();

    fetch('/api/ai/chat/stream',{
      method:'POST',
      headers:jsonHeaders(),
      body:JSON.stringify({
        message:'继续',
        session_id:chatState.sessionId,
        page_content:pageContent,
        images:chatState.lastImages||[],
        use_page_context:chatState.usePageContext,
        model:chatState.selectedModel||'',
        skills:chatState.skills||[],
        deepseek:{web_search:false,read_url:false},
        files:[]
      })
    }).then(function(response){
      if(!response.ok) return httpError(response);
      var reader=response.body.getReader();
      var decoder=new TextDecoder();
      var buffer='';

      function processChunk(){
        return reader.read().then(function(result){
          if(result.done){
            if(!finished){
              finished=true;
              if(renderTimer){ clearTimeout(renderTimer); renderTimer=null; }
              streamEl.innerHTML=refused?escapeHtml(refusalText||'内容未通过安全审核，请调整问题后重试'):renderMarkdown(fullContent||'⚠️ 回复中断，请重试');
              streamBubble.classList.remove('ai-msg-streaming');
              chatState.sending=false;
            }
            return;
          }
          buffer+=decoder.decode(result.value,{stream:true});
          var lines=buffer.split('\n');
          buffer=lines.pop()||'';

          for(var i=0;i<lines.length;i++){
            var line=lines[i].trim();
            if(line.indexOf('data: ')!==0) continue;
            var data;
            try{ data=JSON.parse(line.substring(6)); }catch(e){ continue; }
            if(data.status){
              streamEl.textContent=data.status;
              continue;
            }
            if(data.tool_event){
              setToolStatus(streamBubble,data.tool_event.label||'正在联网…');
              continue;
            }
            if(data.sources){
              sourcesList=data.sources||[];
              continue;
            }
            if(data.refusal){
              // 已流式展示的部分必须撤回：内容审核拒答时整段回答无效
              refused=true;
              refusalText=data.message||'内容未通过安全审核，请调整问题后重试';
              if(renderTimer){ clearTimeout(renderTimer); renderTimer=null; }
              fullContent='';
              streamEl.textContent=refusalText;
              setToolStatus(streamBubble,'');
              continue;
            }
            if(data.error){
              // 同上：error 后无 done 事件，就地复位避免永久锁死
              finished=true;
              if(renderTimer){ clearTimeout(renderTimer); renderTimer=null; }
              streamEl.textContent='⚠️ '+data.error;
              streamBubble.classList.remove('ai-msg-streaming');
              chatState.sending=false;
              break;
            }
            if(data.done){
              finished=true;
              if(renderTimer){ clearTimeout(renderTimer); renderTimer=null; }
              if(refused){
                streamEl.textContent=refusalText||'内容未通过安全审核，请调整问题后重试';
              }else{
                streamEl.innerHTML=renderMarkdown(fullContent);
                renderSources(streamBubble,sourcesList);
              }
              setToolStatus(streamBubble,'');
              streamBubble.classList.remove('ai-msg-streaming');
              if(data.session_id) chatState.sessionId=data.session_id;
              if(data.page_only!==undefined) setPageOnly(data.page_only);
              if(data.truncated){
                var contBtn=document.createElement('button');
                contBtn.className='ai-continue-btn';
                contBtn.textContent='▸ 继续生成';
                contBtn.addEventListener('click',function(){ contBtn.remove(); sendContinueMessage(); });
                streamBubble.querySelector('.ai-msg-bubble-wrap').appendChild(contBtn);
              }
              chatState.sending=false;
              return;
            }
            if(data.content){ fullContent+=data.content; throttledRender(); }
          }
          return processChunk();
        });
      }
      return processChunk();
    }).catch(function(e){
      if(renderTimer){ clearTimeout(renderTimer); renderTimer=null; }
      streamBubble.classList.remove('ai-msg-streaming');
      streamEl.textContent='⚠️ '+((e&&e.userMessage)||'网络错误，请稍后重试');
      chatState.sending=false;
    });
  }

  /* ──── 同步回退发送（用于 regenerate 等）── */
  function sendSync(message){
    if(chatState.sending) return;
    chatState.sending=true;

    addMessage('user',message);
    var loadingBubble=addLoadingMessage();

    var pageContent=getPageContent();

    fetch('/api/ai/chat',{
      method:'POST',
      headers:jsonHeaders(),
      body:JSON.stringify({
        message:message,
        session_id:chatState.sessionId,
        page_content:pageContent,
        images:chatState.lastImages||[],
        use_page_context:chatState.usePageContext,
        model:chatState.selectedModel||'',
        skills:chatState.skills||[]
      })
    }).then(function(r){return r.json();}).then(function(data){
      removeLoadingMessage();
      if(data.success){
        chatState.sessionId=data.session_id;
        if(data.page_only!==undefined) setPageOnly(data.page_only);
        addMessage('assistant',data.reply);
      }else{
        if(data.page_only) setPageOnly(true);
        addMessage('assistant','⚠️ '+data.msg);
      }
      chatState.sending=false;
    }).catch(function(e){
      removeLoadingMessage();
      addMessage('assistant','⚠️ 网络错误，请稍后重试');
      chatState.sending=false;
    });
  }

  /* ──── 操作 ──── */
  function resendMessage(text){ var input=document.getElementById('aiInput'); input.value=text; input.focus(); autoResizeInput(); }

  function toggleImageMode(){
    if(!chatState.imageEnabled) return;
    chatState.imageMode=!chatState.imageMode;
    var btn=document.getElementById('aiImageModeBtn');
    var wrap=document.getElementById('aiOptimizeWrap');
    var input=document.getElementById('aiInput');
    if(btn){
      btn.textContent=chatState.imageMode?'生图：开':'生图：关';
      btn.classList.toggle('ai-context-on',chatState.imageMode);
    }
    if(wrap) wrap.style.display=chatState.imageMode?'inline-flex':'none';
    if(input){
      input.placeholder=chatState.imageMode?'描述你想生成的图片…':'输入消息...';
      input.focus();
    }
  }

  function sendImageMessage(text,opts){
    opts=opts||{};
    if(chatState.sending) return;
    if(!chatState.imageEnabled){
      showCopyToast('生图功能未启用');
      return;
    }
    var input=document.getElementById('aiInput');
    var prompt=text!==undefined&&text!==null?String(text):input.value.trim();
    prompt=prompt.trim();
    if(!prompt) return;
    chatState.lastUserMessage=prompt;
    chatState.lastRequestImage=true;
    chatState.sending=true;
    input.value=''; autoResizeInput();
    if(!opts.reuseUser) addMessage('user',prompt);
    addLoadingMessage();

    fetch('/api/ai/image',{
      method:'POST', headers:jsonHeaders(),
      body:JSON.stringify({
        message:prompt, session_id:chatState.sessionId,
        optimize:chatState.optimizeImage
      })
    }).then(function(r){
      return r.json().catch(function(){ return {}; }).then(function(j){
        if(!r.ok) throw new Error((j&&j.msg)||('生图失败（HTTP '+r.status+'）'));
        return j;
      });
    }).then(function(data){
      removeLoadingMessage();
      if(data.session_id) chatState.sessionId=data.session_id;
      var textPart=data.summary?data.summary+'\n\n':'';
      var imgs=(data.images||[]).map(function(u){ return '![生成图片]('+u+')'; }).join('\n\n');
      addMessage('assistant', textPart+imgs);
      chatState.sending=false;
    }).catch(function(e){
      removeLoadingMessage();
      addMessage('assistant','⚠️ '+(e&&e.message?e.message:'生图失败，请稍后重试'));
      chatState.sending=false;
    });
  }

  function regenerateLastResponse(){
    if(chatState.sending) return;
    var msgDiv=document.getElementById('aiMessages');
    var msgs=msgDiv.querySelectorAll('.ai-msg');
    for(var i=msgs.length-1;i>=0;i--){
      if(msgs[i].getAttribute('data-role')==='assistant'){ msgs[i].remove(); break; }
    }
    var lastUserText=chatState.lastUserMessage;
    if(!lastUserText) return;
    if(chatState.lastRequestImage){
      sendImageMessage(lastUserText,{reuseUser:true});
    }else{
      sendSync(lastUserText);
    }
  }

  function copyToClipboard(text){
    var value=String(text==null?'':text).trim();
    if(!value){ showCopyToast('没有可复制的内容'); return; }
    if(navigator.clipboard){
      navigator.clipboard.writeText(value).then(function(){showCopyToast('已复制');}).catch(function(){fallbackCopy(value);});
    }else{ fallbackCopy(value); }
  }

  function fallbackCopy(text){
    var value=String(text==null?'':text).trim();
    if(!value){ showCopyToast('没有可复制的内容'); return; }
    var ta=document.createElement('textarea');
    ta.value=value; ta.style.position='fixed'; ta.style.left='-9999px'; document.body.appendChild(ta);
    ta.focus(); ta.select();
    var ok=false;
    try{ ok=document.execCommand('copy'); }catch(e){ ok=false; }
    document.body.removeChild(ta);
    showCopyToast(ok?'已复制':'复制失败');
  }

  function showCopyToast(msg){
    var existing=document.querySelector('.ai-toast'); if(existing) existing.remove();
    var toast=document.createElement('div');
    toast.className='ai-toast'; toast.textContent=msg; document.body.appendChild(toast);
    setTimeout(function(){toast.classList.add('show');},10);
    setTimeout(function(){toast.classList.remove('show'); setTimeout(function(){toast.remove();},300);},1500);
  }

  function addLoadingMessage(){
    var msgDiv=document.getElementById('aiMessages');
    var bubble=document.createElement('div');
    bubble.className='ai-msg ai-msg-assistant'; bubble.id='aiLoadingMsg';
    bubble.innerHTML='<div class="ai-msg-avatar"><span>AI</span></div>'+
      '<div class="ai-msg-bubble-wrap"><div class="ai-msg-bubble ai-msg-bubble-assistant"><div class="ai-typing"><span></span><span></span><span></span></div></div></div>';
    msgDiv.appendChild(bubble);
    msgDiv.scrollTop=msgDiv.scrollHeight;
    return bubble;
  }

  function removeLoadingMessage(){ var el=document.getElementById('aiLoadingMsg'); if(el) el.remove(); }

  /* ──── 模型加载 ──── */
  function loadModels(){
    fetch('/api/ai/models').then(function(r){return r.json();}).then(function(data){
      if(!data.success||!data.models||!data.models.length) return;
      chatState.models=data.models;
      var sel=document.getElementById('aiModelSelect'); if(!sel) return;
      var saved=''; try{ saved=localStorage.getItem('aiSelectedModel')||''; }catch(e){}
      var def=data.current||'';
      var hasSaved=saved&&data.models.some(function(m){return m.id===saved;});
      chatState.selectedModel=hasSaved?saved:def;
      sel.innerHTML='';
      data.models.forEach(function(m){
        var opt=document.createElement('option'); opt.value=m.id; opt.textContent=m.name||m.id;
        if(m.id===chatState.selectedModel) opt.selected=true;
        sel.appendChild(opt);
      });
      sel.style.display='';
    }).catch(function(){});
  }

  /* ──── 会话管理 ──── */
  function newChat(){
    if(chatState.sending) return;
    chatState.sessionId='';
    chatState.lastUserMessage='';
    var msgDiv=document.getElementById('aiMessages');
    msgDiv.innerHTML='';
    showWelcome();
  }

  function clearChat(){
    if(chatState.sending) return;
    if(!chatState.sessionId){ newChat(); return; }
    fetch('/api/ai/clear_session',{
      method:'POST', headers:jsonHeaders(),
      body:JSON.stringify({session_id:chatState.sessionId})
    }).then(function(r){return r.json();}).then(function(data){
      chatState.sessionId=''; chatState.lastUserMessage='';
      var msgDiv=document.getElementById('aiMessages'); msgDiv.innerHTML='';
      showWelcome();
    }).catch(function(){ newChat(); });
  }

  function toggleSessionList(){
    if(chatState.sending) return;
    var overlay=document.getElementById('aiSessionOverlay');
    overlay.classList.toggle('show');
    if(overlay.classList.contains('show')) loadSessions();
  }

  function loadSessions(){
    fetch('/api/ai/sessions').then(function(r){return r.json();}).then(function(data){
      var list=document.getElementById('aiSessionList');
      if(!data.success||!data.sessions||data.sessions.length===0){
        list.innerHTML='<div class="ai-session-empty">暂无历史会话</div>'; return;
      }
      list.innerHTML='';
      data.sessions.forEach(function(s){
        var item=document.createElement('div');
        item.className='ai-session-item';
        item.innerHTML='<div class="ai-session-title">'+escapeHtml(s.title)+'</div>'+
          '<div class="ai-session-time">'+s.created_at+'</div>'+
          '<button class="ai-session-del" data-sid="'+s.session_id+'" title="删除"><span class="ai-symbol">×</span></button>';
        item.querySelector('.ai-session-title').onclick=function(){
          if(chatState.sending) return;
          loadSession(s.session_id);
          document.getElementById('aiSessionOverlay').classList.remove('show');
        };
        item.querySelector('.ai-session-del').onclick=function(e){
          e.stopPropagation(); deleteSession(s.session_id);
        };
        list.appendChild(item);
      });
    }).catch(function(){});
  }

  function loadSession(sid){
    if(chatState.sending) return;
    chatState.sessionId=sid;
    var msgDiv=document.getElementById('aiMessages');
    msgDiv.innerHTML='<div class="ai-loading-center">正在思考...</div>';

    fetch('/api/ai/history?session_id='+encodeURIComponent(sid)).then(function(r){return r.json();}).then(function(data){
      msgDiv.innerHTML='';
      if(data.success&&data.messages){
        var lastUser='';
        data.messages.forEach(function(m){
          if(m.role==='user'||m.role==='assistant'){
            addMessage(m.role,m.content);
            if(m.role==='user') lastUser=m.content;
          }
        });
        chatState.lastUserMessage=lastUser;
      }
    }).catch(function(){ msgDiv.innerHTML=''; });
  }

  function deleteSession(sid){
    if(!confirm('确定删除该会话？')) return;
    fetch('/api/ai/clear_session',{
      method:'POST', headers:jsonHeaders(),
      body:JSON.stringify({session_id:sid})
    }).then(function(r){return r.json();}).then(function(data){
      if(data.success){
        if(chatState.sessionId===sid) newChat();
        loadSessions();
      }
    }).catch(function(){});
  }

  function reRenderMessages(){
    // 在 marked 加载完成后重新渲染已存在的消息气泡
    var msgDiv=document.getElementById('aiMessages');
    if(!msgDiv) return;
    var bubbles=msgDiv.querySelectorAll('.ai-msg-assistant .ai-msg-text');
    bubbles.forEach(function(el){
      var raw=el.textContent;
      if(raw) el.innerHTML=renderMarkdown(raw);
    });
  }

  function autoResizeInput(){
    var input=document.getElementById('aiInput'); if(!input) return;
    input.style.height='auto';
    input.style.height=Math.min(input.scrollHeight,100)+'px';
  }

  /* ──── 启动 ──── */
  document.addEventListener('DOMContentLoaded',init);
  if(document.readyState!=='loading') init();

  document.addEventListener('input',function(e){
    if(e.target.id==='aiInput') autoResizeInput();
  });
})();
