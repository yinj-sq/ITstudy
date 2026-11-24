# -*- coding: utf-8 -*-
"""生成铜匠实验室的离线静态导航页（123/铜匠实验室/index.html）。

数据源：123/铜匠实验室/catalog.json（54 门课）。生成结果不依赖网络与
Bootstrap CDN，双击即可浏览（封面/课程均为相对路径）。
"""
import html
import json
import os

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.join(BASE, '123', '铜匠实验室')
CATALOG = os.path.join(ROOT, 'catalog.json')
OUT = os.path.join(ROOT, 'index.html')

SUBJECTS = [('phys', '物理', '#2563eb'), ('chem', '化学', '#0d9488'),
            ('bio', '生物', '#16a34a'), ('geo', '地理', '#d97706')]
SUBJECT_NAME = {k: n for k, n, _ in SUBJECTS}

CSS = """
*{box-sizing:border-box}body{margin:0;font-family:'Microsoft YaHei',system-ui,sans-serif;
background:#f4f7fb;color:#1f2937}
a{color:inherit;text-decoration:none}
.hero{background:linear-gradient(135deg,#0f2027,#203a43 55%,#2c5364);color:#fff;padding:34px 28px}
.hero h1{margin:0 0 8px;font-size:26px}.hero p{margin:4px 0;opacity:.85;font-size:14px}
.wrap{max-width:1280px;margin:0 auto;padding:22px 20px 40px}
.bar{display:flex;flex-wrap:wrap;gap:12px;align-items:center;margin-bottom:16px}
.search{display:flex;align-items:center;gap:8px;background:#fff;border:1px solid #dbe3ee;
border-radius:999px;padding:8px 16px;min-width:260px;flex:0 1 360px}
.search input{border:0;outline:0;width:100%;font-size:14px;background:transparent}
.tabs{display:flex;flex-wrap:wrap;gap:8px}
.tab{border:1px solid #dbe3ee;background:#fff;border-radius:999px;padding:7px 16px;
font-size:14px;cursor:pointer;color:#475569}
.tab.active{background:#0d6efd;border-color:#0d6efd;color:#fff}
.count{font-size:13px;color:#64748b;margin-left:auto}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:16px}
.card{background:#fff;border:1px solid #e2e8f0;border-radius:12px;overflow:hidden;
box-shadow:0 2px 8px rgba(15,23,42,.05);display:flex;flex-direction:column}
.cover{width:100%;aspect-ratio:16/9;object-fit:cover;background:#eef2f5;display:block}
.body{padding:12px 14px 14px;display:flex;flex-direction:column;flex:1}
.card h3{margin:0 0 8px;font-size:15px;line-height:1.4}
.badges{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:8px}
.badge{font-size:11px;color:#475569;background:#f1f5f9;border:1px solid #e2e8f0;
border-radius:999px;padding:2px 8px}
.text{font-size:12px;color:#64748b;line-height:1.5;margin-bottom:8px;
display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.q{color:#92400e}
.enter{margin-top:auto;display:block;text-align:center;background:#0d6efd;color:#fff;
border-radius:999px;padding:8px 12px;font-size:13px}
.footer{margin-top:28px;padding-top:14px;border-top:1px solid #e2e8f0;font-size:12px;
color:#64748b;line-height:1.7}
.hide{display:none!important}
@media(max-width:640px){.hero{padding:24px 18px}.wrap{padding:16px 12px 30px}}
"""

JS = """
(function(){
  var tabs=document.querySelectorAll('.tab');
  var cards=document.querySelectorAll('.card');
  var input=document.getElementById('q');
  var count=document.getElementById('count');
  var active='all';
  function apply(){
    var q=(input.value||'').trim().toLowerCase();
    var shown=0;
    cards.forEach(function(c){
      var okSub=(active==='all'||c.dataset.subject===active);
      var text=(c.dataset.title+' '+c.dataset.textbook+' '+c.dataset.question).toLowerCase();
      var okQ=!q||text.indexOf(q)>=0;
      var show=okSub&&okQ;
      c.classList.toggle('hide',!show);
      if(show)shown++;
    });
    count.textContent=q?('匹配 '+shown+' / '+cards.length+' 门'):('共 '+cards.length+' 门');
  }
  tabs.forEach(function(t){t.addEventListener('click',function(){
    tabs.forEach(function(x){x.classList.remove('active')});
    t.classList.add('active');active=t.dataset.subject;apply();
  })});
  if(input)input.addEventListener('input',apply);
  apply();
})();
"""


def esc(value):
    return html.escape(str(value or ''), quote=True)


def main():
    with open(CATALOG, encoding='utf-8') as f:
        catalog = json.load(f)
    catalog = [c for c in catalog if isinstance(c, dict)]
    catalog.sort(key=lambda c: (c.get('subject', ''), c.get('title', '')))

    tabs = [f'<button class="tab active" data-subject="all">全部 '
            f'<span>{len(catalog)}</span></button>']
    for key, name, _color in SUBJECTS:
        n = sum(1 for c in catalog if c.get('subject') == key)
        if n:
            tabs.append(f'<button class="tab" data-subject="{key}">{name} '
                        f'<span>{n}</span></button>')

    cards = []
    for c in catalog:
        title = esc(c.get('title'))
        subject = c.get('subject', '')
        cover = esc(c.get('cover') or '')
        file_ = esc(c.get('file') or '')
        steps = c.get('steps') or []
        textbook = c.get('textbook') or []
        question = esc(c.get('question') or '')
        ctype = esc(c.get('type') or '3D实验')
        subj_name = SUBJECT_NAME.get(subject, '')
        tb = esc(' '.join(textbook))
        cards.append(f'''
<div class="card" data-subject="{esc(subject)}" data-title="{title}"
     data-textbook="{tb}" data-question="{question}">
  <img class="cover" loading="lazy" src="{cover}" alt="{title}"
       onerror="this.style.display='none'">
  <div class="body">
    <h3>{title}</h3>
    <div class="badges">
      <span class="badge">{subj_name}</span>
      <span class="badge">{ctype}</span>
      <span class="badge">{len(steps)} 步</span>
    </div>
    <div class="text">{esc(textbook[0] if textbook else '')}</div>
    <div class="text q">{question}</div>
    <a class="enter" href="{file_}" target="_blank" rel="noopener">进入实验</a>
  </div>
</div>''')

    page = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>铜匠实验室 · 高中科学 3D 实验（离线导航）</title>
<style>{CSS}</style>
</head>
<body>
<header class="hero">
  <h1>铜匠实验室 · 高中科学 3D 实验</h1>
  <p>免费、可交互的高中科学 3D 实验课件，共 {len(catalog)} 门，覆盖物理、化学、生物、地理。</p>
  <p>外置资源目录：本页不随 ITstudy 安装包分发；课程为自包含 HTML，断网可用。</p>
</header>
<div class="wrap">
  <div class="bar">
    <div class="search"><span>🔍</span>
      <input id="q" type="search" placeholder="输入课程名或教材关键词…">
    </div>
    <div class="tabs">{''.join(tabs)}</div>
    <span class="count" id="count">共 {len(catalog)} 门</span>
  </div>
  <div class="grid">{''.join(cards)}</div>
  <div class="footer">
    课件内容 © 2026 铜匠十点睡觉（lab.tongjiang.app），
    <a href="LICENSE" target="_blank" rel="noopener">CC BY-NC 4.0</a> 许可，
    仅限非商业教学使用；请保留本署名。
  </div>
</div>
<script>{JS}</script>
</body>
</html>'''
    with open(OUT, 'w', encoding='utf-8') as f:
        f.write(page)
    print(f'已生成 {OUT}（{len(catalog)} 门课程）')


if __name__ == '__main__':
    main()
