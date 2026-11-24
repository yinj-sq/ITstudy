/* ============================================================
 * py2blocks.js —— MicroPython 源码 → 积木（逆向转换）
 *
 * 【为什么需要】
 * 老师手上的六年级示例都是 .py 文件（官方 mPython IDE 导出）。
 * 之前打开 .py 只能把源码整个塞进一个「代码积木」，
 * 学生看不到积木、也没法改，改代码更无从谈起。
 * 这里把常见语句还原成真积木，打开就能看懂、就能改。
 *
 * 【覆盖范围】
 *   事件：def on_button_a_pressed(_): → 「当按键 A 被按下」
 *   控制：while True / while not(...) / for ... in range() / if / else
 *   赋值：x = expr → 「把 x 设为 expr」
 *   等待：time.sleep(n) / time.sleep_ms(n)
 *   屏幕：oled.DispChar / oled.show / oled.fill / oled.text
 *   板载：rgb[i] = (...) / rgb.fill(...) / rgb.write()
 *   按键：button_a.is_pressed() / button_a.event_pressed = fn
 *   传感器：ultrasonic.distance() / dht11.temperature() / light.read()
 *   输出：print(...)
 *
 * 还原不了的部分会保留在「代码积木」里，不丢内容。
 * ============================================================ */
(function (global) {
  'use strict';
  var ZKB = global.ZKB || (global.ZKB = {});

  /* ============================================================
   * 一、词法分析：把 py 源码切成记号
   *
   * 【关键】Python 用**缩进**划分语句块，所以换行与缩进信息不能丢。
   * 每个记号都带 nl（前面有几个换行）与 ind（所在行的缩进宽度）。
   * ============================================================ */
  function tokenize(src) {
    var toks = [], i = 0, n = src.length;
    var nl = 0;          /* 累计换行数 */
    var lineStart = true; /* 下一个 token 是否在行首 */
    var indent = 0;       /* 当前行缩进 */
    var KEYWORDS = {
      'if': 'if', 'elif': 'elif', 'else': 'else', 'while': 'while',
      'for': 'for', 'in': 'in', 'def': 'def', 'return': 'return',
      'break': 'break', 'continue': 'continue', 'pass': 'pass',
      'not': 'not', 'and': 'and', 'or': 'or', 'True': 'True', 'False': 'False',
      'None': 'None', 'global': 'global', 'try': 'try', 'except': 'except',
      'finally': 'finally', 'raise': 'raise', 'with': 'with', 'lambda': 'lambda',
      'import': 'import', 'from': 'from', 'as': 'as', 'is': 'is', 'assert': 'assert',
      'del': 'del', 'yield': 'yield', 'class': 'class', 'nonlocal': 'nonlocal'
    };

    function push(t, v, raw) {
      toks.push({ t: t, v: v, raw: raw, nl: nl, ind: indent, lineStart: lineStart });
      nl = 0; lineStart = false;
    }

    while (i < n) {
      var c = src.charAt(i);

      /* 换行：记录行数，缩进留到下次行首处理 */
      if (c === '\n') { i++; nl++; lineStart = true; continue; }
      if (c === '\r') { i++; continue; }

      /* 行首的缩进 */
      if (lineStart) {
        var ind = 0;
        while (i < n) {
          var w = src.charAt(i);
          if (w === ' ') { ind++; i++; continue; }
          if (w === '\t') { ind += 4; i++; continue; }
          break;
        }
        /* 空行（只有缩进没有内容）→ 缩进不生效 */
        if (i >= n) break;
        var nc = src.charAt(i);
        if (nc === '\n') { i++; nl++; continue; }
        if (nc === '\r') { i++; continue; }
        if (nc === '#') { while (i < n && src.charAt(i) !== '\n') i++; continue; }
        indent = ind;
        lineStart = false;
        continue;
      }

      /* 行内空白 */
      if (c === ' ' || c === '\t') { i++; continue; }

      /* 行内注释 */
      if (c === '#') { while (i < n && src.charAt(i) !== '\n') i++; continue; }

      /* 续行（行尾反斜杠）→ 换行不算语句结束 */
      if (c === '\\' && (src.charAt(i + 1) === '\n' || (src.charAt(i + 1) === '\r' && src.charAt(i + 2) === '\n'))) {
        i += (src.charAt(i + 1) === '\n') ? 2 : 3;
        nl++; lineStart = false;
        continue;
      }

      /* 字符串（可跨行，用三引号）
       *
       * 【第四十九轮修正】原来 v 存的是**去掉引号的内容**，
       *   而 parseExprText 是用 t.v 拼表达式的，
       *   于是引号被吞掉：`str('一档')` 变成 `str(一档)`，
       *   下游就把它当成了变量名，而不是字符串。
       *   现在 v 存**带引号的原文**（raw），
       *   让 exprToValue 的「带引号的字符串」分支能正常命中。
       *   内容另存在 s 字段里，需要纯内容时用 t.s。 */
      if (c === '"' || c === "'") {
        var q = c, buf = '', j = i + 1;
        while (j < n && src.charAt(j) !== q) {
          if (src.charAt(j) === '\\') { buf += src.charAt(j + 1); j += 2; continue; }
          if (src.charAt(j) === '\n') { nl++; }
          buf += src.charAt(j); j++;
        }
        var rawStr = src.slice(i, j + 1);
        push('str', rawStr, rawStr);
        /* 内容（不含引号）放在 s 上 */
        toks[toks.length - 1].s = buf;
        i = j + 1;
        continue;
      }

      /* 数字 */
      if (/[0-9]/.test(c) || (c === '.' && /[0-9]/.test(src.charAt(i + 1)))) {
        var k = i;
        while (k < n && /[0-9a-fA-FxX.]/.test(src.charAt(k))) k++;
        push('num', src.slice(i, k));
        i = k;
        continue;
      }

      /* 标识符 / 关键字 */
      if (/[A-Za-z_一-龥]/.test(c)) {
        var m = i;
        while (m < n && /[A-Za-z0-9_一-龥]/.test(src.charAt(m))) m++;
        var w2 = src.slice(i, m);
        push(KEYWORDS[w2] ? 'kw' : 'name', w2);
        i = m;
        continue;
      }

      /* 运算符 */
      var two = src.substr(i, 2);
      if (two === '==' || two === '!=' || two === '<=' || two === '>=' ||
        two === '+=' || two === '-=' || two === '*=' || two === '/=' ||
        two === '//' || two === '**') {
        push('op', two); i += 2; continue;
      }
      /* 运算符
         注意：冒号 ':' 是 Python 的语句分隔符（while True: / if x:），
         绝不能当成除号运算符，否则条件表达式会把后面的整行都吞掉。 */
      if ('+-*/%()[]{},.<>=!'.indexOf(c) >= 0) {
        push('op', c); i++; continue;
      }
      /* 冒号单独作为一种记号，便于语句解析时识别 */
      if (c === ':') {
        push('colon', ':'); i++; continue;
      }
      push('op', c); i++;
    }
    return toks;
  }

  /* ============================================================
  /* ============================================================
   * 二、语法分析：把记号变成语句树
   *
   * Python 用**缩进**划分语句块，所以换行与缩进信息不能丢：
   *   · 一个语句块的缩进 = 它第一条语句的缩进
   *   · 后续缩进更大的行属于这个块
   *   · 缩进变小的行表示块结束
   *
   * 语句节点：
   *   {k:'assign', name, expr}
   *   {k:'if', cond, then:[], else:[]}
   *   {k:'while', cond, body:[]}
   *   {k:'for', var, count, body:[]}
   *   {k:'expr', text}
   *   {k:'func', name, body:[]}
   *   {k:'assignAttr', target, attr, expr}
   *   {k:'assignIdx', target, index, expr}
   * ============================================================ */
  function Parser(toks) {
    this.toks = toks; this.p = 0;
  }
  Parser.prototype.peek = function (off) { return this.toks[this.p + (off || 0)]; };
  Parser.prototype.next = function () { return this.toks[this.p++]; };
  Parser.prototype.eof = function () { return this.p >= this.toks.length; };
  Parser.prototype.at = function (v) {
    var t = this.peek();
    if (!t) return false;
    if (v === ':') return (t.t === 'colon') || (t.t === 'op' && t.v === ':');
    return (t.t === 'op' || t.t === 'kw') && t.v === v;
  };
  Parser.prototype.accept = function (v) {
    if (this.at(v)) { this.p++; return true; }
    return false;
  };
  /* 当前记号的缩进宽度 */
  Parser.prototype.ind = function () {
    var t = this.peek();
    return t ? t.ind : 0;
  };

  /* 表达式：收集成文本
     关键：Python 的语句在**换行**处结束（括号内可以跨行）。
     所以遇到「本记号前面有换行」且当前不在括号里 → 表达式结束。 */
  Parser.prototype.parseExprText = function () {
    var depth = 0, parts = [];
    while (!this.eof()) {
      var t = this.peek();
      /* 记号 nl > 0 表示它前面有换行 → 上一行到这儿结束 */
      if (depth === 0 && t.nl > 0 && parts.length) break;
      if (t.t === 'op' && '([{'.indexOf(t.v) >= 0) { depth++; }
      else if (t.t === 'op' && ')]}'.indexOf(t.v) >= 0) {
        if (depth === 0) break;
        depth--;
      }
      else if (depth === 0 && t.t === 'kw' &&
        ['if', 'while', 'for', 'def', 'return', 'elif', 'else'].indexOf(t.v) >= 0) break;
      else if (depth === 0 && (t.t === 'colon' || (t.t === 'op' && t.v === ':'))) break;
      else if (depth === 0 && t.t === 'op' && t.v === ';') break;
      parts.push(t.v);
      this.p++;
    }
    return parts.join(' ');
  };

  /* 条件表达式 */
  Parser.prototype.parseCond = function () {
    var depth = 0, parts = [];
    while (!this.eof()) {
      var t = this.peek();
      /* 换行处条件结束（括号内可跨行） */
      if (depth === 0 && t.nl > 0 && parts.length) break;
      if (t.t === 'op' && '([{'.indexOf(t.v) >= 0) depth++;
      if (t.t === 'op' && ')]}'.indexOf(t.v) >= 0) {
        if (depth === 0) break;
        depth--;
      }
      if (depth === 0 && (t.t === 'colon' || (t.t === 'op' && t.v === ':'))) break;
      parts.push(t.v);
      this.p++;
    }
    return parts.join(' ');
  };

  /* 跳到行尾（用于 import / try 等整行语句）
     记号的 nl 表示「它自己前面有几个换行」，
     所以要找的是**当前行最后一个记号**：
     从当前位置往后看，第一个 nl > 0 的记号就是下一行的第一个，
     它之前的那个就是本行最后一个。 */
  Parser.prototype.skipToEol = function () {
    while (!this.eof()) {
      var t = this.peek();
      this.p++;
      /* 下一个记号前面有换行 → 本行到此结束 */
      var nx = this.peek();
      if (!nx || nx.nl > 0) return;
    }
  };

  /* 解析一组语句：缩进 >= baseInd 的都算这个块 */
  Parser.prototype.parseBlock = function (baseInd) {
    var stmts = [];
    if (baseInd === undefined) {
      /* 顶层：跳过 import / from / global 等，基准缩进取第一条有效语句 */
      while (!this.eof()) {
        var t0 = this.peek();
        if (t0.t === 'kw' && ['import', 'from', 'global', 'pass'].indexOf(t0.v) >= 0) {
          this.skipToEol(); stmts.push({ k: 'skip' }); continue;
        }
        break;
      }
      if (this.eof()) return stmts;
      baseInd = this.ind();
    }

    while (!this.eof()) {
      var t = this.peek();
      /* 缩进小于基准 → 块结束 */
      if (t.ind < baseInd) break;
      var st = this.parseStmt();
      if (!st) break;
      stmts.push(st);
      /* 防御：一条语句解析完若缩进反而变浅，说明块已结束 */
      if (!this.eof() && this.ind() < baseInd) break;
    }
    return stmts;
  };

  Parser.prototype.parseStmt = function () {
    if (this.eof()) return null;
    var t = this.peek();

    /* def 函数定义 */
    if (t.t === 'kw' && t.v === 'def') {
      /* 记住 def 自身的缩进：函数体的基准 = def 的缩进 + 1。
         ⚠ 不能用 this.ind()——那时指针已移到下一条记号，
         拿到的是「块内第一条语句」的缩进（更大），会把函数体判空。 */
      var defInd = t.ind;
      this.p++;
      var name = this.next().v;
      if (this.at('(')) {
        var d = 0;
        while (!this.eof()) {
          var x = this.next();
          if (x.t === 'op' && x.v === '(') d++;
          if (x.t === 'op' && x.v === ')') { d--; if (d === 0) break; }
        }
      }
      if (this.at(':')) this.p++;
      var body = this.parseBlock(defInd + 1);
      return { k: 'func', name: name, body: body };
    }

    /* if */
    if (t.t === 'kw' && t.v === 'if') {
      var ifInd = t.ind;
      this.p++;
      var cond = this.parseCond();
      if (this.at(':')) this.p++;
      var base = ifInd;
      var thenB = this.parseBlock(base + 1);
      var elseB = [];
      var nx = this.peek();
      if (nx && nx.t === 'kw' && nx.v === 'elif' && nx.ind === base) {
        elseB = [this.parseStmt()];
      } else if (nx && nx.t === 'kw' && nx.v === 'else' && nx.ind === base) {
        this.p++;
        if (this.at(':')) this.p++;
        elseB = this.parseBlock(base + 1);
      }
      return { k: 'if', cond: cond, then: thenB, else: elseB };
    }

    /* while */
    if (t.t === 'kw' && t.v === 'while') {
      var whileInd = t.ind;
      this.p++;
      var wcond = this.parseCond();
      if (this.at(':')) this.p++;
      var wbase = whileInd;
      var wbody = this.parseBlock(wbase + 1);
      return { k: 'while', cond: wcond, body: wbody };
    }

    /* for */
    if (t.t === 'kw' && t.v === 'for') {
      var forInd = t.ind;
      this.p++;
      var vn = this.next().v;
      if (this.peek() && this.peek().v === 'in') this.p++;
      var cnt = this.parseExprText();
      if (this.at(':')) this.p++;
      var fbase = forInd;
      var fbody = this.parseBlock(fbase + 1);
      return { k: 'for', var: vn, count: cnt, body: fbody };
    }

    /* import / from / global / pass / try…：跳过 */
    if (t.t === 'kw' && ['import', 'from', 'global', 'pass', 'try', 'except',
      'finally', 'raise', 'with', 'assert', 'del', 'class', 'nonlocal',
      'break', 'continue', 'return'].indexOf(t.v) >= 0) {
      if (t.v === 'pass') { this.p++; return { k: 'skip' }; }
      if (t.v === 'global') {
        /* global jvli / global a, b
           后面没有冒号，必须按行尾结束，
           否则会一路吃到下一个冒号，把整条 while 语句都吃掉 */
        this.p++;
        this.skipToEol();
        return { k: 'skip' };
      }
      if (t.v === 'break' || t.v === 'continue' || t.v === 'return') {
        this.p++;
        this.parseExprText();
        return { k: 'skip' };
      }
      /* 单行 try：官方示例里定时器回调常写成
         `try: dht11.measure()`（一行写完），
         整行丢掉的话传感器刷新就丢了。
         这里只在「冒号后同一行还有语句」时把那条语句解析出来。 */
      if (t.v === 'try') {
        this.p++;
        if (this.at(':')) this.p++;
        var nt = this.peek();
        if (nt && nt.nl === 0 && !(nt.t === 'kw' && (nt.v === 'except' || nt.v === 'finally'))) {
          return this.parseStmt();
        }
        return { k: 'skip' };
      }
      this.skipToEol();
      return { k: 'skip' };
    }

    /* 赋值：obj.attr = 表达式 */
    if (t.t === 'name' && this.peek(1) && this.peek(1).t === 'op' && this.peek(1).v === '.') {
      var isAttr = false;
      for (var q2 = 2; q2 < 14; q2++) {
        var tk2 = this.peek(q2);
        if (!tk2) break;
        if (tk2.t === 'op' && tk2.v === '=') { isAttr = true; break; }
        if (tk2.t === 'op' && (tk2.v === '(' || tk2.v === '[')) break;
      }
      if (isAttr) {
        var obj = this.next().v;
        this.p++;   /* . */
        var attr = this.next().v;
        this.p++;   /* = */
        var ex2 = this.parseExprText();
        return { k: 'assignAttr', target: obj, attr: attr, expr: ex2 };
      }
    }

    /* 赋值：obj[i] = 表达式 */
    if (t.t === 'name' && this.peek(1) && this.peek(1).t === 'op' && this.peek(1).v === '[') {
      var obj2 = this.next().v;
      this.p++;   /* [ */
      var idx = '';
      var d2 = 1;
      while (!this.eof() && d2 > 0) {
        var tk3 = this.next();
        if (tk3.t === 'op' && tk3.v === '[') d2++;
        if (tk3.t === 'op' && tk3.v === ']') { d2--; if (d2 === 0) break; }
        idx += tk3.v;
      }
      if (this.at('=')) {
        this.p++;
        var ex3 = this.parseExprText();
        return { k: 'assignIdx', target: obj2, index: idx.trim(), expr: ex3 };
      }
    }

    /* 赋值：name = 表达式 */
    if (t.t === 'name' && this.peek(1) && this.peek(1).t === 'op' && this.peek(1).v === '=') {
      var nm = this.next().v;
      this.p++;   /* = */
      var expr = this.parseExprText();
      return { k: 'assign', name: nm, expr: expr };
    }

    /* 裸表达式语句 */
    if (t.t === 'num' || t.t === 'str' || t.t === 'name' || t.t === 'op') {
      var e = this.parseExprText();
      if (e) return { k: 'expr', text: e };
    }
    this.p++;
    return { k: 'skip' };
  };

  /* ============================================================
   * 三、表达式 → 值积木
   * ============================================================ */

  function mkText(text) {
    return '<shadow type="text"><field name="TEXT">' + esc(text) + '</field></shadow>';
  }
  function mkNum(num) {
    return '<shadow type="math_number"><field name="NUM">' + esc(num) + '</field></shadow>';
  }
  function mkBool(v) {
    return '<shadow type="logic_boolean"><field name="BOOL">' + v + '</field></shadow>';
  }
  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }
  function escAttr(s) {
    return esc(s).replace(/"/g, '&quot;');
  }

  /* 表达式文本 → 值积木 XML
     识别：数字 / 字符串 / 变量 / 函数调用
     wantNum = true 时优先产出数字影子块
     （坐标、尺寸这些口都是 check:'Number'，
       给成 text 影子块 Blockly 会拒绝连接，块就飘在工作区里） */
  function exprToValue(text, wantNum) {
    var t = String(text || '').trim();
    /* 词法分析用空格拼记号，先把点号/括号旁的空格去掉 */
    t = t.replace(/\s*([.\[\]()])\s*/g, '$1').replace(/\s+/g, ' ').trim();
    if (!t) return wantNum ? mkNum('0') : mkText('');
    /* 数字 */
    if (/^-?\d+(\.\d+)?$/.test(t)) return mkNum(t);
    /* 布尔 */
    if (t === 'True') return mkBool('TRUE');
    if (t === 'False') return mkBool('FALSE');
    /* 带引号的字符串 */
    var sm = t.match(/^(['"])([\s\S]*)\1$/);
    if (sm) return mkText(sm[2]);
    /* 去掉一层多余括号 */
    if (t.charAt(0) === '(' && t.charAt(t.length - 1) === ')' && balanced(t.slice(1, -1))) {
      return exprToValue(t.slice(1, -1));
    }
    /* 变量（简单名字） */
    if (/^[A-Za-z_一-龥][A-Za-z0-9_一-龥]*$/.test(t)) {
      return '<block type="variables_get"><field name="VAR" id="' +
        escAttr(varId(t)) + '">' + esc(t) + '</field></block>';
    }
    /* 传感器 / 板载读取的调用 → 对应的值积木 */
    var sensor = callToValue(t);
    if (sensor) return sensor;
    /* str(...) —— 转字符串
     * 【第四十九轮修正】原来 str() 没有被识别，
     *   落到了兜底分支变成文本 "str(距离)"，
     *   生成的代码就成了 oled.DispChar(str('str(距离)')…) —— 双层包裹，
     *   屏幕上会显示出 "str(距离)" 这种怪东西。
     *   现在把 str() 剥掉，里面的内容再递归解析：
     *     str('一档')  → 文本「一档」
     *     str(距离)    → 变量「距离」
     *     str(25)      → 数字 25 */
    var stm = t.match(/^str\s*\(([\s\S]*)\)$/);
    if (stm) {
      var inner = stm[1].trim();
      /* str('x') —— 字符串字面量，直接取内容 */
      var innerStr = inner.match(/^(['"])([\s\S]*)\1$/);
      if (innerStr) return mkText(innerStr[2]);
      return exprToValue(inner, wantNum);
    }
    /* int(x) —— 取整
     * 【第四十九轮新增】官方示例里到处是
     *   brightness = int(9) / 亮度 = int(255*brightness//9)
     * 原来不识别，整个表达式被当成**文本**塞进变量，
     * 生成的代码是 brightness = 'int(9)' —— 后面拿它算数直接崩。
     * int() 只是"转成整数"，对积木来说等于去掉这层壳。 */
    var im = t.match(/^int\s*\(([\s\S]*)\)$/);
    if (im) return exprToValue(im[1].trim(), wantNum);
    /* round(x) → 四舍五入（Blockly 内置 math_round）
     * ⚠ math_round 的 NUM 口是 check:'Number'，
     *   里面必须也是**数值**积木。如果内层没解析出来（比如还认不出的函数），
     *   一定要把 wantNum 传下去让它退化成 math_number，
     *   否则会塞一个 text 影子块进去 → Blockly 拒绝连接 →
     *   影子块游离 → 渲染时抛 "The text content is null."，整份工程打不开。 */
    var rm = t.match(/^round\s*\(([\s\S]*)\)$/);
    if (rm) {
      return '<block type="math_round"><field name="OP">ROUND</field>' +
        '<value name="NUM">' + exprToValue(rm[1].trim(), true) + '</value></block>';
    }
    /* math.sqrt(x) → 开平方（Blockly 内置 math_single 的 ROOT） */
    var sq = t.match(/^math\.sqrt\s*\(([\s\S]*)\)$/);
    if (sq) {
      return '<block type="math_single"><field name="OP">ROOT</field>' +
        '<value name="NUM">' + exprToValue(sq[1].trim(), true) + '</value></block>';
    }
    /* math.pow(a, b) → 乘方
     * 【第四十九轮新增】官方「加速度传感器强度值.py」里
     *   三轴强度 = sqrt(x² + y² + z²)，全靠 pow/sqrt，
     *   原来认不出，整句被当成文本，学生看到的积木完全不对。 */
    var pw = splitCallArgs(t, 'math.pow');
    if (pw && pw.length >= 2) {
      return '<block type="math_arithmetic"><field name="OP">POWER</field>' +
        '<value name="A">' + exprToValue(pw[0], true) + '</value>' +
        '<value name="B">' + exprToValue(pw[1], true) + '</value></block>';
    }
    /* hunan_map_value(x, in_min, in_max, out_min, out_max) → 映射积木
       这是本项目生成器自己注入的映射函数（与官方六年级示例同名），
       还原时要变回「把…从…映射到…」积木，不能降级成文本。 */
    var mv = splitCallArgs(t, 'hunan_map_value');
    if (mv && mv.length >= 5) {
      return '<block type="zk_map_value">' +
        '<value name="X">' + exprToValue(mv[0], true) + '</value>' +
        '<value name="A">' + exprToValue(mv[1], true) + '</value>' +
        '<value name="B">' + exprToValue(mv[2], true) + '</value>' +
        '<value name="C">' + exprToValue(mv[3], true) + '</value>' +
        '<value name="D">' + exprToValue(mv[4], true) + '</value>' +
        '</block>';
    }
    /* 四则运算 → math_arithmetic
     * 【第四十九轮新增】彩灯亮度几乎都是算出来的：
     *   rgb[0] = (int(255*brightness//9), int(0*brightness//9), …)
     * 原来不识别 → 三个通道全变成 0 → 真机上灯根本不亮。
     * ⚠ Python 的 // 是整除，Blockly 的 DIVIDE 生成的是 /（浮点）。
     *   直接映射会让 NeoPixel 拿到浮点数，所以 // 额外套一层 math_round。 */
    var ar = splitTopOp(t, ['+', '-']) || splitTopOp(t, ['//', '**', '*', '/', '%']);
    if (ar) {
      return arithToValue(ar.op, ar.a, ar.b);
    }
    /* 其它：当作文本（数值口则给数字影子，避免接不上） */
    if (wantNum) return mkNum('0');
    return mkText(t);
  }

  /* 在最外层（括号外）切分二元运算符
     从右往左找，保证 a - b - c 这类也能切。
     ops 里长的要排在前面（'//' 必须比 '/' 先试），
     否则会把 '//' 当成两个单独的 '/'。 */
  function splitTopOp(t, ops) {
    var d = 0;
    for (var i = t.length - 1; i >= 0; i--) {
      var c = t.charAt(i);
      if (c === ')') d++;
      else if (c === '(') d--;
      else if (d === 0) {
        for (var k = 0; k < ops.length; k++) {
          var op = ops[k];
          if (t.substr(i, op.length) !== op) continue;
          var left = t.slice(0, i).trim();
          var right = t.slice(i + op.length).trim();
          /* 左边为空 → 这是一元正负号（-5），不是运算 */
          if (!left || !right) continue;
          /* 左边以运算符结尾 → 也是一元（如 2 * -3） */
          if (/[+\-*/%]$/.test(left)) continue;
          return { op: op, a: left, b: right };
        }
      }
    }
    return null;
  }

  /* 一个二元运算 → math_arithmetic（// 再套一层 round） */
  function arithToValue(op, a, b) {
    var OP = { '+': 'ADD', '-': 'MINUS', '*': 'MULTIPLY', '/': 'DIVIDE', '%': 'MODULO',
      '**': 'POWER' }[op] || 'ADD';
    var xml = '<block type="math_arithmetic"><field name="OP">' + OP + '</field>' +
      '<value name="A">' + exprToValue(a, true) + '</value>' +
      '<value name="B">' + exprToValue(b, true) + '</value></block>';
    if (op === '//') {
      /* 整除 = 除完再取整，避免 NeoPixel 收到浮点 */
      xml = '<block type="math_round"><field name="OP">ROUND</field>' +
        '<value name="NUM">' + xml + '</value></block>';
    }
    return xml;
  }

  /* 判断括号是否平衡 */
  function balanced(s) {
    var d = 0;
    for (var i = 0; i < s.length; i++) {
      if (s.charAt(i) === '(') d++;
      if (s.charAt(i) === ')') { d--; if (d < 0) return false; }
    }
    return d === 0;
  }

  /* ============================================================
   * 四、语句树 → 积木 XML
   * ============================================================ */
  var SEQ = 0;
  /* 已解析到的函数：名字 → 函数体语句数组 */
  var FUNCS = {};
  /* 变量名 → 变量 id（field_variable 必须带 id 才能绑定变量） */
  var VARIDS = {};

  /* 取（并登记）一个变量的 id
     ⚠ field_variable 的字段必须带 id：
       没有 id 时 Blockly 绑定不到变量，this.variable 为 null，
       渲染时会抛 "The text content is null."，整份工程都打不开。 */
  function varId(name) {
    var k = String(name || '');
    if (!k) return 'pyvar_0';
    if (!VARIDS[k]) VARIDS[k] = 'pyvar_' + k;
    return VARIDS[k];
  }

  /* 按名字取函数体（找不到就返回空） */
  function funcBodyOf(name) {
    var key = String(name || '').trim();
    return FUNCS[key] || [];
  }

  /* 判断一个表达式是不是「调用本文件里定义的自定义函数」
   *
   * 【第四十九轮新增】官方示例大量使用自定义函数，
   * 例如小车转弯.py：
   *     def 直线():
   *         parrot.set_speed(parrot.MOTOR_1, 50)
   *     def on_button_a_pressed(_):
   *         while not (...):
   *             直线()
   * 如果只是把「直线()」当成一条打印语句，
   * 函数体里的电机控制就全丢了 —— 真机上小车根本不会动。
   * 所以这里识别出自定义函数调用，**把函数体就地展开**。 */
  function customFuncCall(text) {
    var t = String(text || '').trim()
      .replace(/\s*([.\[\]()])\s*/g, '$1').replace(/\s+/g, ' ').trim();
    var m = t.match(/^([A-Za-z_一-龥][A-Za-z0-9_一-龥]*)\s*\(\s*\)$/);
    if (!m) return null;
    var name = m[1];
    if (!FUNCS[name]) return null;
    /* 防止函数自己调用自己造成无限递归 */
    if (EXPANDING[name]) return null;
    return name;
  }

  /* 正在展开中的函数名（防递归） */
  var EXPANDING = {};

  /* 定时器回调的函数体（见 case 'expr' 里 timXX.init 的说明）
     记下来之后塞进紧随其后的 `while True:` 循环开头。 */
  var TIMER_BODY = [];

  /* 把语句列表里的「自定义函数调用」就地展开成函数体
   *
   * 【第四十九轮修正】原来是在 stmtToBlock 里用 chainAppend()
   * 把函数体的 XML 拼到 next 链上。chainAppend 靠字符串找
   * `</block>` 定位链尾，而函数体本身是多块嵌套的
   * `<block><next><block>…</next></block>`，
   * 它把「链中间的 </next>」误判成「末尾已有 next」，直接 return，
   * 于是**这条语句之后的所有语句都被静默丢掉**。
   *   自动避障.py 就是这样：展开「启动()」之后，
   *   整个 `while not (button_b.is_pressed())` 循环和「停车()」全没了，
   *   真机上小车只会加速一下然后停下，完全不巡线。
   *
   * 改成在**语句列表层面**展开：调用语句直接替换成函数体的若干条语句，
   * 后面该接什么还接什么，不存在 XML 字符串拼接。
   * 递归处理 if / while / for 的子块，天然支持函数嵌套调用。 */
  function flattenCalls(stmts, depth) {
    if (depth > 10) return stmts || [];
    var out = [];
    (stmts || []).forEach(function (st) {
      if (!st) return;
      if (st.k === 'skip') { out.push(st); return; }
      /* 函数定义：登记「正在展开」，防止 A→B→A 互调死循环 */
      if (st.k === 'func') {
        EXPANDING[st.name] = true;
        st.body = flattenCalls(st.body || [], depth + 1);
        delete EXPANDING[st.name];
        out.push(st);
        return;
      }
      /* 函数调用 → 替换成函数体 */
      if (st.k === 'expr') {
        var cf = customFuncCall(st.text);
        if (cf) {
          /* slice() 复制一份，避免展开结果污染 FUNCS 里的原始函数体 */
          var body = flattenCalls((funcBodyOf(cf) || []).slice(), depth + 1);
          body.forEach(function (b) { out.push(b); });
          return;
        }
      }
      /* 子块递归展开 */
      if (st.then) st.then = flattenCalls(st.then, depth + 1);
      if (st.else) st.else = flattenCalls(st.else, depth + 1);
      if (st.body) st.body = flattenCalls(st.body, depth + 1);
      out.push(st);
    });
    return out;
  }

  /* 一条语句 → 一个积木的 XML（含 next 链） */
  function stmtToBlock(st, nextXml) {
    var id = 'py' + (SEQ++);
    var inner = '';
    var type = '';
    var attrs = '';
    /* nextXml 用局部变量：事件帽子分支要往里插函数体 */
    var nx = nextXml;

    switch (st.k) {
      case 'assign': {
        /* 硬件初始化语句（不是真正的赋值）：
             ultrasonic = Ultrasonic()
             p1 = MPythonPin(1, PinMode.IN)
             tim15 = Timer(15)
             servo_0 = Servo(0, min_us=500, …)
             dht11 = dht.DHT11(Pin(Pin.P13))
           【第四十九轮修正】原来降级成「打印」，生成
             print('ultrasonic = Ultrasonic ( )')
           这种话——真机上只会往串口打一行字，硬件压根没初始化。
           实际上 gen-python 会**根据用到了哪些积木**自动在头文件里
           重新生成这些初始化语句（`from bluebit import *` +
           `ultrasonic = Ultrasonic()` / `pin_1 = MPythonPin(1, PinMode.IN)` …），
           所以这里**直接跳过**即可，既不误导学生又不会多出垃圾代码。 */
        if (/^[A-Z]\w*\s*\(/.test(String(st.expr).trim()) ||
            /^\w+\.[A-Z]\w*\s*\(/.test(String(st.expr).trim())) {
          return nextXml || '';
        }
        type = 'variables_set';
        inner = '<field name="VAR" id="' + escAttr(varId(st.name)) + '">' +
          esc(st.name) + '</field>' +
          '<value name="VALUE">' + exprToValue(st.expr) + '</value>';
        break;
      }
      case 'expr': {
        /* 词法分析用空格拼记号，匹配前先紧化 */
        var e = st.text.replace(/\s*([.\[\]()])\s*/g, '$1').replace(/\s+/g, ' ').trim();
        /* oled.DispChar(str(...), x, y, size) → 屏幕显示文字
           官方四参数：内容、X、Y、字号。
           注意参数里可能含逗号（如 (int(1) - 1) * 16），
           所以要按「括号外的逗号」拆分，不能用简单正则。 */
        var dcArgs = splitCallArgs(e, 'oled.DispChar');
        if (dcArgs && dcArgs.length >= 3) {
          type = 'zk_oled_text';
          inner = '<value name="T">' + exprToValue(dcArgs[0]) + '</value>' +
            '<value name="X">' + exprToValue(dcArgs[1], true) + '</value>' +
            '<value name="Y">' + exprToValue(dcArgs[2], true) + '</value>';
          break;
        }
        var ot = e.match(/oled\.text\s*\(\s*(.+?)\s*,\s*(-?[\d(].*?)\s*,\s*(-?[\d(].*?)\s*\)$/);
        if (ot) {
          type = 'zk_oled_text';
          inner = '<value name="T">' + exprToValue(ot[1]) + '</value>' +
            '<value name="X">' + exprToValue(ot[2], true) + '</value>' +
            '<value name="Y">' + exprToValue(ot[3], true) + '</value>';
          break;
        }
        if (/^oled\.show\s*\(\s*\)$/.test(e)) { type = 'zk_oled_show'; break; }
        if (/^oled\.fill\s*\(\s*0\s*\)$/.test(e)) { type = 'zk_oled_clear'; break; }
        var of = e.match(/^oled\.fill\s*\(\s*(\d+)\s*\)$/);
        if (of) {
          type = 'zk_oled_fill';
          attrs = '<field name="V">' + of[1] + '</field>';
          break;
        }
        /* rgb[i] = (...) → 彩灯 */
        var rgbI = e.match(/^rgb\s*\[\s*(\d+)\s*\]\s*=\s*\((.*)\)$/);
        if (rgbI) {
          type = 'zk_rgb_rgb';
          attrs = '<field name="N">' + rgbI[1] + '</field>';
          /* R/G/B 是数值口 → 用 math_number 影子块 */
          inner = '<value name="R">' + exprToValue(rgbI[2].split(',')[0] || '0', true) + '</value>' +
            '<value name="G">' + exprToValue(rgbI[2].split(',')[1] || '0', true) + '</value>' +
            '<value name="B">' + exprToValue(rgbI[2].split(',')[2] || '0', true) + '</value>';
          break;
        }
        /* rgb.fill((r, g, b)) → 设置彩灯颜色
         * 【第四十九轮修正】原来不管参数是什么都当成 zk_rgb_clear（清空），
         *   官方示例里 rgb.fill((255,0,0)) 是"点亮红色彩灯"，
         *   被还原成"清空彩灯" —— 行为完全错了。 */
        var rgbFill = e.match(/^rgb\.fill\s*\(\s*\((.*)\)\s*\)$/);
        if (rgbFill) {
          var fp = rgbFill[1].split(',');
          type = 'zk_rgb_rgb';
          attrs = '<field name="N">ALL</field>';
          inner = '<value name="R">' + exprToValue(fp[0] || '0', true) + '</value>' +
            '<value name="G">' + exprToValue(fp[1] || '0', true) + '</value>' +
            '<value name="B">' + exprToValue(fp[2] || '0', true) + '</value>';
          break;
        }
        if (/^rgb\.fill\s*\(\s*\(?\s*0\s*,?\s*0\s*,?\s*0\s*\)?\s*\)$/.test(e)) {
          type = 'zk_rgb_clear';
          break;
        }
        if (/^rgb\.fill\s*\(/.test(e)) {
          type = 'zk_rgb_clear';
          break;
        }
        if (/^rgb\.write\s*\(\s*\)$/.test(e)) {
          type = 'zk_rgb_write';
          break;
        }
        /* time.sleep(n) / time.sleep_ms(n) */
        var sl = e.match(/^time\.sleep_ms\s*\(\s*(.+?)\s*\)$/);
        if (sl) {
          type = 'zk_wait_ms';
          inner = '<value name="MS">' + exprToValue(sl[1]) + '</value>';
          break;
        }
        var sl2 = e.match(/^time\.sleep\s*\(\s*(.+?)\s*\)$/);
        if (sl2) {
          type = 'zk_wait_sec';
          inner = '<value name="SEC">' + exprToValue(sl2[1]) + '</value>';
          break;
        }
        /* p1.write_digital(1) → 设置数字引脚输出
         * 【第四十九轮新增】官方示例（自动孵蛋箱等）用
         *   MPythonPin(1, PinMode.OUT) 建引脚，再 write_digital 控制加热元件。
         *   之前没有对应积木，只能塞进「打印」，真机上加热元件根本不会动。 */
        var pwd = e.match(/^p(\d+)\.write_digital\s*\(\s*(.+?)\s*\)$/);
        if (pwd) {
          type = 'zk_pin_dout';
          var lvl = String(pwd[2]).trim();
          /* PIN 下拉的值是纯编号（'1'），显示文本才是 'P1' */
          attrs = '<field name="PIN">' + pwd[1] + '</field>' +
            '<field name="V">' + (/^(0|False)$/.test(lvl) ? '0' : '1') + '</field>';
          break;
        }
        /* print(...) */
        var pr = e.match(/^print\s*\(\s*(.*)\s*\)$/);
        if (pr) {
          type = 'zk_print';
          inner = '<value name="V">' + exprToValue(pr[1]) + '</value>';
          break;
        }
        /* parrot.set_speed(parrot.MOTOR_1, 60) → 拓展板电机速度
         * 【第四十九轮新增】官方示例（节能风扇、自动避障等）大量使用
         * 拓展板电机，之前没有对应积木，只能塞进「打印」，
         * 生成的代码是 print('parrot.set_speed(...)') —— 真机上完全没用。 */
        var psp = e.match(/^parrot\.set_speed\s*\(\s*parrot\.MOTOR_(\d)\s*,\s*(.+?)\s*\)$/);
        if (psp) {
          type = 'zk_parrot_speed';
          attrs = '<field name="MOTOR">MOTOR_' + psp[1] + '</field>';
          inner = '<value name="SPD">' + exprToValue(psp[2], true) + '</value>';
          break;
        }
        /* servo.write_angle(servo.P0, 90) → 舵机角度 */
        var swa = e.match(/^servo\.write_angle\s*\(\s*servo\.P(\d)\s*,\s*(.+?)\s*\)$/);
        if (swa) {
          type = 'zk_servo';
          inner = '<value name="A">' + exprToValue(swa[2], true) + '</value>';
          break;
        }
        /* 【第四十九轮新增】music 模块的几个调用
         * 官方六年级示例（声光贺卡 / 时间提醒器 / 模拟洗衣机 / 坐姿监控器）
         * 大量使用内置乐曲，原来全部降级成 print，真机上一点声音都没有。 */
        var mstop = /^music\.stop\s*\(\s*\)$/.test(e);
        if (mstop) { type = 'zk_music_stop'; break; }
        var mmel = splitCallArgs(e, 'music.play');
        if (mmel && mmel.length) {
          /* music.play(music.BIRTHDAY, wait=False, loop=True) */
          var mel = String(mmel[0]).trim().match(/^music\.([A-Z_0-9]+)$/i);
          if (mel) {
            var kw = String(mmel.slice(1).join(','));
            var wait = /wait\s*=\s*True/i.test(kw) || mmel.length === 1;
            var loop = /loop\s*=\s*True/i.test(kw);
            var mode = (wait ? (loop ? 'loopWait' : 'once') : (loop ? 'bgLoop' : 'bgOnce'));
            type = 'zk_music_melody';
            attrs = '<field name="NAME">' + mel[1].toUpperCase() + '</field>' +
              '<field name="MODE">' + mode + '</field>';
            break;
          }
          /* music.play(['C4:4'], wait=False) —— 单个音符的列表写法，
             直接还原成「播放音符 C4 节拍 4」（zk_note 生成的就是它） */
          /* ⚠ 'C4:4' 是「音名:节拍」，冒号在**引号里面**，
             别写成 ['"]:…（那是 music.play('C4:4') 的写法） */
          var note = String(mmel[0]).trim().match(/^\[\s*['"]([A-Ga-g]#?\d)\s*:\s*([\d.]+)['"]?\s*\]$/);
          if (note) {
            type = 'zk_note';
            attrs = '<field name="NOTE">' + note[1].toUpperCase() + '</field>' +
              '<field name="BEAT">' + note[2] + '</field>';
            break;
          }
        }
        /* music.pitch(频率, 时长) → 蜂鸣器音调 */
        var mpt = splitCallArgs(e, 'music.pitch');
        if (mpt && mpt.length) {
          type = 'zk_music_pitch';
          inner = '<value name="P">' + exprToValue(mpt[0], true) + '</value>';
          break;
        }
        /* servo_0.write_angle(180) —— 官方示例用带编号的舵机对象名，
           原来只认 servo.write_angle(servo.P0, 90) 这种写法 */
        var swa2 = e.match(/^servo_?\d*\.write_angle\s*\(\s*(.+?)\s*\)$/);
        if (swa2) {
          type = 'zk_servo';
          inner = '<value name="A">' + exprToValue(swa2[1], true) + '</value>';
          break;
        }
        /* 定时器初始化：tim15.init(period=1000, mode=Timer.PERIODIC, callback=timer15_tick)
         * 【第四十九轮新增】官方示例用定时器**周期性地**刷新传感器
         * （节能风扇 / 自动孵蛋箱 / 读取温度值 里都是 1 秒刷一次 DHT11）。
         * 积木体系里没有定时器积木，直接丢掉会让温度一直是旧值。
         * 做法：跳过这条 init，但把回调函数的函数体记下来，
         * 塞进紧随其后的 `while True:` 循环体开头 ——
         * 每轮循环刷新一次，语义与 1 秒定时刷新等价。 */
        var tinit = e.match(/^tim\d+\.init\s*\(/);
        if (tinit) {
          var cb = e.match(/callback\s*=\s*([A-Za-z_]\w*)/);
          if (cb) TIMER_BODY = (funcBodyOf(cb[1]) || []).filter(function (s) { return s && s.k !== 'skip'; });
          return nextXml || '';
        }
        /* 自定义函数调用：已由 flattenCalls 在语句列表层面展开，
           走到这儿说明没展开成功（自递归 / 层数超限），兜底成打印。 */
        /* parrot.led(0, 1) 之类暂不识别，落到兜底 */
        /* 其它：塞进打印 */
        type = 'zk_print';
        inner = '<value name="V">' + mkText(e) + '</value>';
        break;
      }
      case 'assignIdx': {
        type = 'zk_rgb_rgb';
        attrs = '<field name="N">' + esc(st.index) + '</field>';
        var parts = splitArgs(st.expr.replace(/\s*([.\[\]()])\s*/g, '$1'));
        /* R/G/B 口都是 check:'Number'，必须给 math_number 影子块。
           给成 text 影子块 Blockly 会拒绝连接，
           那个影子块就变成游离块，渲染时抛 "The text content is null."。 */
        inner = '<value name="R">' + exprToValue(parts[0] || '0', true) + '</value>' +
          '<value name="G">' + exprToValue(parts[1] || '0', true) + '</value>' +
          '<value name="B">' + exprToValue(parts[2] || '0', true) + '</value>';
        break;
      }
      case 'assignAttr': {
        /* button_a.event_pressed = fn → 「当按键 A 被按下」
           注意：本项目的事件帽子（zk_when_btn / zk_when_touch）
           只有 nextStatement，**没有 statement 口**——
           帽子下面��内容是 next 链上的积木，不是 statement。
           所以函数体要接到 next 链上（见下面的 nextXml 处理）。 */
        var bm = st.target.match(/^button_([ab])$/i);
        if (bm && st.attr === 'event_pressed') {
          type = 'zk_when_btn';
          attrs = '<field name="BTN">' + bm[1].toUpperCase() + '</field>';
          inner = '';
          /* 函数体接到帽子的 next 链上，
             函数体之后再接原来排在这条语句之后的积木（nx） */
          nx = chainAppend(stmtsToChain(funcBodyOf(st.expr)), nx);
          break;
        }
        /* touchPad_X.event_pressed → 「当触摸引脚 X 被触摸」 */
        var tm = st.target.match(/^touchPad_([PYTHON])$/i);
        if (tm && st.attr === 'event_pressed') {
          type = 'zk_when_touch';
          attrs = '<field name="PAD">' + tm[1].toUpperCase() + '</field>';
          inner = '';
          nx = chainAppend(stmtsToChain(funcBodyOf(st.expr)), nx);
          break;
        }
        type = 'zk_print';
        inner = '<value name="V">' + mkText(st.target + '.' + st.attr + ' = ' + st.expr) + '</value>';
        break;
      }
      case 'if': {
        type = 'controls_if';
        inner = '<value name="IF0">' + condToValue(st.cond) + '</value>';
        inner += '<statement name="DO0">' + stmtsToChain(st.then) + '</statement>';
        if (st.else && st.else.length) {
          inner += '<mutation else="1"></mutation>';
          inner += '<statement name="ELSE">' + stmtsToChain(st.else) + '</statement>';
        }
        break;
      }
      case 'while': {
        var c = st.cond.replace(/^\s*not\s*\(/, '').replace(/\)\s*$/, '').trim();
        /* while not (cond) → 重复执行直到 cond 成立
         *
         * ⚠【第四十九轮修正】controls_whileUntil 有 MODE 字段，
         *   默认是 **WHILE**（"当条件成立时重复"）。
         *   不写 MODE=UNTIL 的话，`while not (X)` 会被还原成
         *   `while X` —— 条件取反丢失，程序行为完全反了！
         *   （真机跑起来就是死循环 / 立刻退出）
         */
        if (/^not\s*\(/.test(st.cond)) {
          type = 'controls_whileUntil';
          inner = '<field name="MODE">UNTIL</field>' +
            '<value name="BOOL">' + condToValue(c) + '</value>' +
            '<statement name="DO">' + stmtsToChain(st.body) + '</statement>';
        } else {
          type = 'controls_forever';
          /* 定时器回调的函数体插到循环体开头（每轮刷新一次传感器） */
          var body = st.body || [];
          if (TIMER_BODY.length) {
            body = TIMER_BODY.concat(body);
            TIMER_BODY = [];
          }
          inner = '<statement name="SUBSTACK">' + stmtsToChain(body) + '</statement>';
        }
        break;
      }
      case 'for': {
        type = 'controls_for';
        var cm = st.count.match(/range\s*\(\s*(.+?)\s*\)$/);
        inner = '<value name="FROM">' + mkNum('0') + '</value>' +
          '<value name="TO">' + exprToValue(cm ? cm[1] : st.count) + '</value>' +
          '<value name="BY">' + mkNum('1') + '</value>' +
          '<statement name="DO">' + stmtsToChain(st.body) + '</statement>';
        break;
      }
      case 'func': {
        /* 函数体登记到 FUNCS，等「button_a.event_pressed = 函数名」
           那行出现时挂到事件帽子下面。函数本身不单独生成积木。 */
        FUNCS[st.name] = st.body || [];
        return nextXml || '';
      }
      default:
        return nextXml || '';
    }

    return '<block type="' + type + '" id="' + id + '">' + attrs + inner +
      (nx ? '<next>' + nx + '</next>' : '') + '</block>';
  }

  /* 把 tail 接到 chain 最后一个积木的后面
     chain 是「倒序拼出来」的 next 链：
       <block A><next><block B>…</next></block>
     末尾的块没有 <next>，正好用来接 tail。 */
  function chainAppend(chain, tail) {
    if (!tail) return chain || '';
    if (!chain) return tail;
    /* 找到最后一个 <block …> 的结束位置（末尾没有 <next>） */
    var idx = chain.lastIndexOf('</block>');
    if (idx < 0) return chain;
    /* 该块后面还有 <next> 吗？ */
    var head = chain.slice(0, idx);
    var hasNext = /<next>[\s\S]*<\/next>$/.test(head);
    if (hasNext) {
      /* 最后一个块已经有 next 了 → 说明链尾不是它，插到 next 之前不合适。
         这种情况在 stmtsToChain 里不会出现（倒序拼装，最后一个块必无 next）。 */
      return chain;
    }
    return chain.slice(0, idx) + '<next>' + tail + '</next>' + chain.slice(idx);
  }

  /* 判断这条语句是不是「事件帽子」（要独立成链，不能接在别人后面） */
  function isHatStmt(st) {
    if (!st) return false;
    if (st.k === 'assignAttr') {
      var bm = st.target.match(/^button_([ab])$/i);
      if (bm && st.attr === 'event_pressed') return true;
      var tm = st.target.match(/^touchPad_([PYTHON])$/i);
      if (tm && st.attr === 'event_pressed') return true;
    }
    return false;
  }

  /* 语句数组 → next 链
     帽子块（事件帽子）要独立成链：它不能接在别的块后面，
     也不能把后面的普通块接在自己后面。 */
  function stmtsToChain(stmts) {
    /* 先把自定义函数调用展开成函数体（见 flattenCalls 说明） */
    stmts = flattenCalls(stmts || [], 0);
    var hatXml = '', plainXml = '';
    for (var i = stmts.length - 1; i >= 0; i--) {
      var st = stmts[i];
      if (!st || st.k === 'skip') continue;
      if (isHatStmt(st)) {
        /* 帽子块：自己成一条链，不接前后任何块 */
        hatXml = stmtToBlock(st, '') + (hatXml ? hatXml : '');
      } else {
        plainXml = stmtToBlock(st, plainXml);
      }
    }
    return hatXml + plainXml;
  }

  /* 条件文本 → 值积木 */
  function condToValue(cond) {
    var t = String(cond || '').trim();
    /* 词法分析把每个记号用空格拼起来了，
       匹配函数调用前先把「点号 / 括号前后的空格」去掉 */
    var tight = t.replace(/\s*([.\[\]()])\s*/g, '$1').replace(/\s+/g, ' ').trim();
    /* 比较：a op b */
    var cm = tight.match(/^(.+?)\s*(==|!=|<=|>=|<|>)\s*(.+)$/);
    if (cm && balanced(cm[1])) {
      return '<block type="logic_compare">' +
        '<field name="OP">' + cmpOp(cm[2]) + '</field>' +
        '<value name="A">' + exprToValue(cm[1]) + '</value>' +
        '<value name="B">' + exprToValue(cm[3]) + '</value>' +
        '</block>';
    }
    /* 逻辑与 / 或 */
    var am = tight.match(/^(.+?)\s+and\s+(.+)$/);
    if (am && balanced(am[1])) {
      return '<block type="logic_operation">' +
        '<field name="OP">AND</field>' +
        '<value name="A">' + condToValue(am[1]) + '</value>' +
        '<value name="B">' + condToValue(am[2]) + '</value>' +
        '</block>';
    }
    var om = tight.match(/^(.+?)\s+or\s+(.+)$/);
    if (om && balanced(om[1])) {
      return '<block type="logic_operation">' +
        '<field name="OP">OR</field>' +
        '<value name="A">' + condToValue(om[1]) + '</value>' +
        '<value name="B">' + condToValue(om[2]) + '</value>' +
        '</block>';
    }
    /* 函数调用 → 板载传感器 */
    var sensor = callToValue(tight);
    if (sensor) return sensor;
    /* ⚠ 条件口（BOOL）是 check:'Boolean'，
       给 text 影子块会被 Blockly 拒绝连接 → 影子块游离 → 渲染崩。
       这里给 logic_boolean 影子块，保证类型对得上。 */
    return mkBool('FALSE');
  }

  function cmpOp(op) {
    return { '==': 'EQ', '!=': 'NEQ', '<=': 'LTE', '>=': 'GTE', '<': 'LT', '>': 'GT' }[op] || 'EQ';
  }

  /* 常见调用 → 值积木 */
  function callToValue(t) {
    /* 超声波测距 */
    var u = t.match(/^ultrasonic\.distance\s*\(\s*\)$/);
    if (u) return '<block type="zk_ultra"></block>';
    /* 温湿度 */
    var d = t.match(/^dht11\.temperature\s*\(\s*\)$/);
    if (d) return '<block type="zk_dht_val"><field name="K">t</field></block>';
    var dh = t.match(/^dht11\.humidity\s*\(\s*\)$/);
    if (dh) return '<block type="zk_dht_val"><field name="K">h</field></block>';
    /* 光线 / 声音 */
    if (/^light\.read\s*\(\s*\)$/.test(t)) return '<block type="zk_light"></block>';
    if (/^sound\.read\s*\(\s*\)$/.test(t)) return '<block type="zk_sound"></block>';
    /* 按键 */
    var b = t.match(/^button_([ab])\.is_pressed\s*\(\s*\)$/i);
    if (b) return '<block type="zk_is_btn"><field name="BTN">' + b[1].toUpperCase() + '</field></block>';
    /* 触摸 */
    var p = t.match(/^touchPad_([PYTHON])\.is_pressed\s*\(\s*\)$/);
    if (p) return '<block type="zk_is_touch"><field name="PAD">' + p[1] + '</field></block>';
    /* 加速度 */
    var a = t.match(/^accelerometer\.get_([xyz])\s*\(\s*\)$/);
    if (a) return '<block type="zk_accel"><field name="AXIS">' + a[1] + '</field></block>';
    /* 【第四十九轮新增】官方示例用 MPythonPin 建的引脚：
         p1 = MPythonPin(1, PinMode.IN)   …   p1.read_digital()
       本项目生成的是 pin_1 = MPythonPin(1, PinMode.IN)（头文件自动生成），
       所以这里只要把引脚号取出来做成 zk_pin_din / zk_pin_ain 即可。 */
    var pr = t.match(/^p(\d+)\.read_digital\s*\(\s*\)$/);
    if (pr) return '<block type="zk_pin_din"><field name="PIN">' + pr[1] + '</field></block>';
    var pa = t.match(/^p(\d+)\.read_analog\s*\(\s*\)$/);
    if (pa) return '<block type="zk_pin_ain"><field name="PIN">' + pa[1] + '</field></block>';
    return null;
  }

  /* 拆分「函数名(参数, 参数, …)」的调用参数
     按括号外的逗号切分，参数内部可以有逗号（嵌套调用） */
  function splitCallArgs(text, fnName) {
    var t = String(text || '').trim();
    var i = t.indexOf(fnName);
    if (i < 0) return null;
    var lp = t.indexOf('(', i);
    if (lp < 0) return null;
    /* 从左括号一直取到**最后一个**右括号
       （参数里可能还有嵌套括号，如 str(距离)） */
    var rp = t.lastIndexOf(')');
    if (rp <= lp) return null;
    return splitArgs(t.slice(lp + 1, rp));
  }

  /* 拆分 (a, b, c) 里的参数 */
  function splitArgs(s) {
    var t = String(s || '').trim();
    if (t.charAt(0) === '(' && t.charAt(t.length - 1) === ')') t = t.slice(1, -1);
    var out = [], depth = 0, buf = '';
    for (var i = 0; i < t.length; i++) {
      var c = t.charAt(i);
      if ('([{'.indexOf(c) >= 0) depth++;
      if (')]}'.indexOf(c) >= 0) depth--;
      if (c === ',' && depth === 0) { out.push(buf.trim()); buf = ''; continue; }
      buf += c;
    }
    if (buf.trim()) out.push(buf.trim());
    return out;
  }

  /* 净化 XML：给空的 <field> 补上占位文本 */
  function sanitizeXml(xml) {
    var s = String(xml || '');
    /* <field name="X"></field> → <field name="X">0</field>
       <field name="X"/>    → <field name="X">0</field> */
    s = s.replace(/<field([^>]*?)(\s*\/?)>/g, function (all, attrs, slash) {
      /* 已经自闭合的补成 <field ...></field> */
      if (slash === '/') return '<field' + attrs + '>0</field>';
      return all;
    });
    /* 再把紧邻的空 field 填上内容 */
    s = s.replace(/<field([^>]*)><\/field>/g, '<field$1>0</field>');
    return s;
  }

  /* ============================================================
   * 五、对外接口
   * ============================================================ */

  /* 语句树 → 完整 XML 字符串
     parse 与调试接口共用，保证两边行为完全一致 */
  function buildXml(stmts) {
    /* 预登记所有函数：事件帽子（button_a.event_pressed = fn）
       可能写在函数定义之前，先把函数体都收进来 */
    FUNCS = {};
    EXPANDING = {};
    TIMER_BODY = [];
    stmts.forEach(function (s) {
      if (s && s.k === 'func') FUNCS[s.name] = s.body || [];
    });

    /* 还原成积木链
       ⚠ 帽子块（zk_when_btn / zk_when_touch）**不能**接在别的块后面，
         Blockly 的 Zelos 渲染器遇到「帽子块有 previousConnection」
         会抛 "The text content is null."，整份工程都打不开。
         stmtsToChain 内部已把帽子块拆成独立的一条链。 */
    var chain = stmtsToChain(stmts);
    if (!chain) return '';

    /* 变量声明要放在链之后生成：
       链里的 field_variable 会调用 varId() 登记变量 id，
       声明里的 id 必须和 field 里的完全一致。 */
    var vars = {};
    stmts.forEach(function (s) { collectVars(s, vars); });
    var varXml = '';
    Object.keys(vars).forEach(function (v) {
      varXml += '<variable id="' + escAttr(varId(v)) + '">' + esc(v) + '</variable>';
    });

    return sanitizeXml('<xml xmlns="https://developers.google.com/blockly/xml">' +
      (varXml ? '<variables>' + varXml + '</variables>' : '') +
      chain + '</xml>');
  }

  function parse(ws, py) {
    try {
      SEQ = 0;
      VARIDS = {};
      var src = String(py || '');
      /* 去掉 mPython 的标记行 */
      src = src.replace(/^\s*#mPythonType:\d+\s*$/m, '');
      var toks = tokenize(src);
      var p = new Parser(toks);
      var stmts = p.parseBlock();

      /* 还原成积木链（buildXml 里会预登记函数、生成变量声明、净化 XML） */
      var xml = buildXml(stmts);
      if (!xml) return { ok: false, reason: '没有识别出可还原的语句' };

      var dom = Blockly.utils.xml.textToDom(xml);
      Blockly.Xml.domToWorkspace(dom, ws);
      return { ok: true, count: ws.getAllBlocks(false).length };
    } catch (e) {
      return { ok: false, reason: e.message };
    }
  }

  function collectVars(st, out) {
    if (!st) return;
    if (st.k === 'assign' && st.name) out[st.name] = varId(st.name);
    if (st.k === 'func') (st.body || []).forEach(function (s) { collectVars(s, out); });
    if (st.k === 'if') {
      (st.then || []).forEach(function (s) { collectVars(s, out); });
      (st.else || []).forEach(function (s) { collectVars(s, out); });
    }
    if (st.k === 'while' || st.k === 'for') (st.body || []).forEach(function (s) { collectVars(s, out); });
  }

  ZKB.Py2Blocks = {
    parse: parse,
    tokenize: tokenize,
    /* 调试用 */
    _funcs: function(){ return FUNCS; },
    _xmlOf: function (py) {
      try {
        SEQ = 0; FUNCS = {}; VARIDS = {};
        var src = String(py || '').replace(/^\s*#mPythonType:\d+\s*$/m, '');
        var p = new Parser(tokenize(src));
        return buildXml(p.parseBlock());
      } catch (e) { return 'ERR ' + e.message; }
    },
    _chainOf: function(stmts){ return stmtsToChain(stmts); },
    _blockOf: function(st){ return stmtToBlock(st, ''); },
    splitCallArgs: splitCallArgs,
    splitArgs: splitArgs,
    /* 调试用：只解析不建积木，返回语句树 */
    parseTree: function (py) {
      try {
        SEQ = 0; FUNCS = {};
        var src = String(py || '').replace(/^\s*#mPythonType:\d+\s*$/m, '');
        var p = new Parser(tokenize(src));
        return p.parseBlock();
      } catch (e) { return { error: e.message }; }
    }
  };

})(window);
