/* ============================================================
 * serial-link.js —— Web Serial 真机连接（MicroPython raw REPL）
 * 支持：连接 / 断开 / 写入 main.py 并运行 / REPL 临时运行
 * 浏览器要求：Chrome / Edge 等基于 Chromium 的浏览器（HTTPS 或 localhost）
 * ============================================================ */
(function (global) {
  'use strict';
  var ZKB = global.ZKB || (global.ZKB = {});

  var port = null, writer = null, reader = null;
  var rx = '';                 // 接收缓冲
  var pumpActive = false;
  var enc = new TextEncoder();
  var dec = new TextDecoder();

  function log(v, cls) { (ZKB.log || console.log)(v, cls || 'log-hw'); }

  /* ---------------- 状态指示 ---------------- */
  function setUI(connected) {
    var dot = document.getElementById('conn-dot');
    var txt = document.getElementById('conn-text');
    if (dot) dot.style.background = connected ? '#3ddc84' : '#e0553b';
    if (txt) txt.textContent = connected ? '已连接：掌控板' : '连接设备';
  }

  function isSupported() { return !!navigator.serial; }
  function isConnected() { return !!port; }

  /* ---------------- 接收泵 ---------------- */
  function startPump() {
    if (pumpActive || !port || !port.readable) return;
    pumpActive = true;
    reader = port.readable.getReader();
    (function pump() {
      reader.read().then(function (res) {
        if (res.done) { pumpActive = false; return; }
        /* 解码失败（罕见：串口错误 / 数据异常）不能让接收泵就此死掉，
         * 否则后面所有响应都收不到，表现为「设备返回为：(空)」。
         * 这里单独 try 住解码异常，继续读下一块。 */
        try {
          rx += dec.decode(res.value, { stream: true });
        } catch (e) {
          /* 忽略这一块，继续读 */
        }
        pump();
      }).catch(function (err) {
        /* 读失败：串口断开或被系统回收。
         * 标记泵已停，并提示用户，避免"静默失联"。 */
        pumpActive = false;
        if (port) {
          log('串口读取中断：' + (err && err.message || err) +
            '（如果设备被拔掉，请重新点击「连接设备」）', 'log-err');
          setUI(false);
        }
      });
    })();
    // 空闲输出：未被命令消费的串口文本直接进控制台
    setInterval(function () {
      if (!port || !rx) return;
      /* 命令交互期间绝对不抢输出。
       * ⚠ 之前只看「距上次命令 900ms」，但一次 raw REPL 命令
       *   （尤其上传大程序）常常要好几秒，
       *   等到 900ms 后这个定时器就会把我们要的响应当成
       *   普通串口输出冲进控制台，导致「设备返回为：(空)」。
       *   现在用显式的 cmdBusy 标志，命令期间完全让路。 */
      if (cmdBusy) return;
      if (Date.now() - lastCmdAt < 900) return;
      var s = rx; rx = '';
      var lines = cleanLines(s);
      lines.forEach(function (line) { log('[串口] ' + line, 'log-hw'); });
      /* 第二十四轮：串口输出同时显示在舞台「掌控小助手」旁边的气泡里 */
      if (lines.length && ZKB.Stage && ZKB.Stage.say) {
        ZKB.Stage.say(lines.slice(-3).join('\n'));
      }
    }, 600);
  }

  var lastCmdAt = 0;
  /* 命令进行中标志：为真时，空闲输出泵不许抢 rx */
  var cmdBusy = false;
  function cleanLines(s) {
    return s.replace(/\x1b\[[0-9;]*[A-Za-z]/g, '').replace(/\r/g, '')
      .split('\n').map(function (x) { return x.trim(); }).filter(Boolean);
  }

  /* 等待终止符或超时，返回截取到的文本
     （保留给控制台空闲输出用；raw REPL 协议走 waitUntil / readBytes） */
  function waitFor(term, timeout) {
    lastCmdAt = Date.now();
    return new Promise(function (resolve) {
      var t0 = Date.now();
      var iv = setInterval(function () {
        var i = term ? rx.indexOf(term) : -1;
        if (i >= 0) {
          clearInterval(iv);
          var out = rx.slice(0, i + term.length);
          rx = rx.slice(i + term.length);
          lastCmdAt = Date.now();
          resolve(out);
        } else if (Date.now() - t0 > timeout) {
          clearInterval(iv);
          var rest = rx; rx = '';
          lastCmdAt = Date.now();
          resolve(rest);
        }
      }, 15);
    });
  }
  function sleep(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }

  async function send(str) {
    if (!writer) throw new Error('串口未打开，请先点击「连接设备」');
    var bytes = typeof str === 'string' ? enc.encode(str) : str;
    /* 分块写入，避免撑爆 ESP32 串口缓冲
     *
     * 【必须 await write】writer.write() 返回一个 Promise，
     * 表示这批字节已交给底层缓冲。之前没 await 就直接 sleep，
     * 下一块可能还没写完就发了，串口缓冲一满就**丢字节**，
     * 表现为设备收到的命令残缺 → 语法错误或无响应。
     * 这也是上传大程序时最容易出问题的地方。 */
    var CHUNK = 128;
    for (var i = 0; i < bytes.length; i += CHUNK) {
      await writer.ready;
      await writer.write(bytes.subarray(i, i + CHUNK));
      /* 给 ESP32 一点时间把字节搬走（115200 波特率下 128 字节约 11ms） */
      await sleep(12);
    }
  }

  /* ---------------- 连接 / 断开 ---------------- */
  async function connect() {
    if (!isSupported()) {
      log('当前浏览器不支持 Web Serial，请使用 Chrome / Edge 浏览器，或先用「下载 .py」方式手动烧录。', 'log-err');
      ZKB.toast && ZKB.toast('请使用 Chrome / Edge 浏览器连接硬件');
      return false;
    }
    try {
      port = await navigator.serial.requestPort();
    } catch (e) {
      log('未选择串口：' + e.message, 'log-info');
      return false;
    }
    try {
      await port.open({ baudRate: 115200, dataBits: 8, stopBits: 1, flowControl: 'none' });
      writer = port.writable.getWriter();
      rx = '';
      /* 关键：换设备时必须重启接收泵。
       * 上一次的泵如果还活着（pumpActive 为 true），
       * startPump 会直接 return，新设备的 reader 就不会被创建，
       * 数据永远收不到 —— 表现就是「连上了但上传没反应」。
       * 这里先把旧泵停掉再启动新的。 */
      try { if (reader) { await reader.cancel(); } } catch (e) { }
      reader = null;
      pumpActive = false;
      startPump();
      setUI(true);
      log('串口已打开（115200），正在唤醒掌控板…', 'log-ok');
      /* 中断当前程序并回到 REPL
       * 官方 repl.py 的做法是 \r\n\x03\x03（先回车清行，再两次 Ctrl-C），
       * 只发一次 Ctrl-C 有可能打断不干净 —— 设备还在跑旧程序时，
       * 后面的 raw REPL 握手就会失败。 */
      await send('\r\n\x03\x03');
      await sleep(400);
      /* 清掉设备可能吐出的残留（运行日志、Traceback 等） */
      rx = '';
      await send('\r\n');
      await sleep(150);
      rx = '';
      log('连接成功，可以上传代码到掌控板了。', 'log-ok');
      ZKB.toast && ZKB.toast('掌控板连接成功');
      return true;
    } catch (e) {
      log('串口打开失败：' + e.message + '（请检查驱动与端口占用）', 'log-err');
      try { await teardown(); } catch (x) {}
      return false;
    }
  }

  async function teardown() {
    try { writer && await writer.close(); } catch (e) {}
    try { reader && await reader.cancel(); } catch (e) {}
    try { port && await port.close(); } catch (e) {}
    writer = null; reader = null; port = null; pumpActive = false;
    setUI(false);
  }
  async function disconnect() {
    if (port) { await send('\x03\r\n').catch(function () {}); await teardown(); log('已断开与掌控板的连接。', 'log-info'); }
  }

  /* ---------------- raw REPL 交互 ----------------
   *
   * 【协议来源】参考 mPython 官方固件的 repl.py
   *   参考资料/mpython-master（mpython掌控板文档和固件源码）/
   *   mpython-master/port/boards/labplus_1956/modules/repl.py
   * 固件侧的实现在 port/lib/utils/pyexec.c。
   *
   * 【raw REPL 的完整时序】
   *   1. \r\n\x03\x03   两次 Ctrl-C 中断正在运行的程序，并回车清行
   *   2. 清空输入缓冲   官方做法：读掉 inWaiting() 里所有残留字节
   *   3. \r\n\x01       回车后发 Ctrl-A，进入 raw REPL
   *   4. 等横幅         "raw REPL; CTRL-B to exit\r\n>"
   *   5. import os + \x04 + 读响应   官方称"预热"，避免第一条命令被吞
   *   6. 发命令 + \x04   设备先回 "OK"，再回 stdout\x04stderr\x04>
   *
   * 【之前失败的原因】
   *   - 只发一次 \x03、且不清输入缓冲 → 设备可能还在跑旧程序，
   *     没真正进入 raw REPL，我们却照样发命令；
   *   - 没检查设备回的 "OK" → 进不去也往下走；
   *   - 响应格式理解错了：设备回的是 OK<out>\x04<err>\x04>，
   *     stdout 与 stderr 之间有一个 \x04，我们只等 "\x04>"，
   *     把两段混在一起，最后 out 为空 → 报"设备返回为：(空)"。
   */

  /* 从 rx 里取走前 n 个字节（按字符近似，协议里都是 ASCII 控制字符） */
  function takeBytes(n) {
    var s = rx.slice(0, n);
    rx = rx.slice(n);
    return s;
  }

  /* 等待 rx 里出现 term。
   *
   * 【重要】返回 { text, found }：
   *   text  是 term **之前**的文本（term 本身被吃掉）
   *   found 是有没有真的等到 term
   * ⚠ 之前这里只返回文本，导致调用方拿不到 term 就去判断内容
   *   （比如拿「raw REPL; CTRL-B to exit」横幅去 indexOf('raw REPL')），
   *   永远判断不到 → 握手必然失败。
   */
  function waitUntil(term, timeout) {
    lastCmdAt = Date.now();
    return new Promise(function (resolve) {
      var t0 = Date.now();
      var iv = setInterval(function () {
        /* 每次轮询都刷新时间戳：让「空闲输出泵」在等待期间保持安静，
           不要把我们要的响应当普通串口输出抢走。 */
        lastCmdAt = Date.now();
        var i = rx.indexOf(term);
        if (i >= 0) {
          clearInterval(iv);
          var out = rx.slice(0, i);
          rx = rx.slice(i + term.length);
          lastCmdAt = Date.now();
          resolve({ text: out, found: true });
        } else if (Date.now() - t0 > timeout) {
          clearInterval(iv);
          var rest = rx; rx = '';
          lastCmdAt = Date.now();
          resolve({ text: rest, found: false });
        }
      }, 10);
    });
  }

  /* 读满 n 个字节（不足则等到超时，返回实际读到的） */
  function readBytes(n, timeout) {
    lastCmdAt = Date.now();
    return new Promise(function (resolve) {
      var t0 = Date.now();
      var iv = setInterval(function () {
        lastCmdAt = Date.now();
        if (rx.length >= n) {
          clearInterval(iv);
          var out = takeBytes(n);
          lastCmdAt = Date.now();
          resolve(out);
        } else if (Date.now() - t0 > timeout) {
          clearInterval(iv);
          var rest = rx; rx = '';
          lastCmdAt = Date.now();
          resolve(rest);
        }
      }, 10);
    });
  }

  /* 进入 raw REPL，成功返回 true
   *
   * 官方 repl.py 的 enter_raw_repl 步骤：
   *   ① \r\n\x03\x03   两次 Ctrl-C 中断正在运行的程序
   *   ② 读掉 inWaiting() 里所有残留字节（清输入缓冲）
   *   ③ \r\n\x01       回车 + Ctrl-A 进入 raw REPL
   *   ④ 等横幅 "raw REPL; CTRL-B to exit\r\n>"
   *   ⑤ import os + \x04 + follow(10)   预热，防止第一条命令被吞
   */
  async function enterRaw() {
    rx = '';
    /* ① 两次 Ctrl-C 中断正在运行的程序；先回车清掉半行输入 */
    await send('\r\n\x03\x03');
    await sleep(250);
    /* ② 清空设备侧的输入缓冲（官方做法，避免残留干扰） */
    await send('\r\n');
    await sleep(100);
    rx = '';
    /* ③ 回车 + Ctrl-A 进入 raw REPL */
    await send('\r\n\x01');
    /* ④ 等完整横幅（found 才是真的等到了） */
    var banner = await waitUntil('raw REPL; CTRL-B to exit\r\n>', 2500);
    if (!banner.found) {
      /* 兜底重试：Ctrl-A 可能被前面的残留吞掉，
         这时用 Ctrl-B 强制退出可能存在的 raw 模式，再来一次。 */
      rx = '';
      await send('\x02');
      await sleep(150);
      await send('\r\n\x03\x03');
      await sleep(200);
      rx = '';
      await send('\r\n\x01');
      banner = await waitUntil('raw REPL; CTRL-B to exit\r\n>', 2500);
      if (!banner.found) return false;
    }
    /* ⑤ 预热：执行一条 import os，把这条响应的 \x04 收干净，
          否则后面的命令会把它当成自己的输出。 */
    await send('import os');
    await send('\x04');
    await readBytes(2, 2000);      // "OK"
    await waitUntil('\x04', 2000); // stdout 结束
    await waitUntil('\x04', 2000); // stderr 结束
    return true;
  }

  // 退出 raw REPL 回友好 REPL
  async function exitRaw() {
    await send('\r\x02');           // 回车 + Ctrl-B
    await sleep(150);
  }

  /* 在 raw REPL 中执行一段 Python，返回 { out, err, ok } */
  async function rawExec(code, timeout) {
    if (!port) return { out: '', err: '串口未连接', ok: false };
    /* 命令进行中：空闲输出泵这段时间不许抢 rx */
    cmdBusy = true;
    try {
      var ok = await enterRaw();
      if (!ok) {
        return {
          out: '', ok: false,
          err: '未能进入 raw REPL（请按一下掌控板的复位键，让它回到「>>>」提示符后再试）'
        };
      }
      rx = '';
      await send(code);
      await sleep(60);
      await send('\x04');             // Ctrl-D：执行

      /* 设备先回 "OK"，表示命令已被接收 */
      var head = await readBytes(2, timeout || 8000);
      if (head !== 'OK') {
        await exitRaw();
        return {
          out: '', ok: false,
          err: '设备未确认接收命令（期望 "OK"，实际收到：' +
            JSON.stringify(head || '(空)') + '）'
        };
      }
      /* 然后是 stdout\x04stderr\x04> */
      var out = await waitUntil('\x04', timeout || 8000);
      var err = await waitUntil('\x04', timeout || 8000);
      return { out: (out.text || '').trim(), err: (err.text || '').trim(), ok: true };
    } finally {
      cmdBusy = false;
    }
  }

  /* ---------------- 高层操作 ---------------- */

  /* 把一段 UTF-8 字节转成 Python bytes 字面量的**内容部分**
   * （不含外层引号）
   *
   * 【为什么不用 base64】官方 repl.py 的 fs_put 用的是
   *   w(b'\x00\x01...')  —— 直接写字节字面量。
   * 设备端执行 f.write(b'...') 时用的是二进制模式，
   * 中文按 UTF-8 字节写入，和官方完全一致。
   * base64 需要设备端有 ubinascii 模块（虽然官方固件里确实有），
   * 直接写字节字面量更稳，也不怕模块缺失。
   *
   * 【转义规则】对每一字节：
   *   - 0x20~0x7e 且不是 ' 和 \  → 原样输出
   *   - 其余 → \xNN（两位小写十六进制）
   * ' 和 \ 一定要转义，否则会提前闭合字符串 / 变成转义符。 */
  function toPyBytesContent(bytes) {
    var out = '';
    for (var i = 0; i < bytes.length; i++) {
      var c = bytes[i];
      if (c >= 0x20 && c <= 0x7e && c !== 0x27 && c !== 0x5c) {
        out += String.fromCharCode(c);
      } else {
        out += '\\x' + ('0' + c.toString(16)).slice(-2);
      }
    }
    return out;
  }

  /* 把 UTF-8 字符串编码成字节数组 */
  function utf8Bytes(str) {
    var enc = new TextEncoder();
    return enc.encode(str);
  }

  /* 把字节数组切成若干块，每块**在字节层面**切开
   *
   * 【关键：为什么必须在字节层面切】
   *   之前是「先整体转义 → 再按字符数切」，这样切点可能落在
   *   一个 \xNN 转义序列中间（\x + 两位十六进制），
   *   切出来的片段以 "\x" 结尾，Python 解析 b'...\x' 时
   *   转义不完整 → SyntaxError: invalid syntax。
   *   （真机报错就是：File "<stdin>", line 1 SyntaxError）
   *   现在改成「先按字节切 → 每块独立转义」，
   *   转义序列永远不会跨块，问题从根上消失。 */
  function splitBytes(bytes, chunkSize) {
    var res = [];
    for (var i = 0; i < bytes.length; i += chunkSize) {
      res.push(bytes.subarray(i, Math.min(i + chunkSize, bytes.length)));
    }
    return res;
  }

  /* 写入 main.py 并软复位运行
   *
   * 【为什么要分块、但只握手一次】
   *   - 分块：一段程序可能几千字节，一次发一条超长命令，
   *     设备端 vstr 缓冲区容易不够，串口也容易丢字节；
   *   - 只握手一次：rawExec 每调用一次都会重新握手（发 \x03\x03 等），
   *     分块时反复握手会把刚打开的文件句柄状态打乱，
   *     而且慢得离谱。所以这里自己管理一次会话。 */
  async function uploadAndRun(pyCode) {
    if (!port && !(await connect())) return false;
    log('开始上传程序到掌控板（写入 main.py）…', 'log-hw');
    cmdBusy = true;
    try {
      /* 【关键】先按 UTF-8 字节切块，再逐块独立转义。
         如果先整体转义再切，切点可能落在 \xNN 中间，
         切出的片段以 "\x" 结尾 → Python 报
         File "<stdin>", line 1 SyntaxError: invalid syntax。 */
      var bytes = utf8Bytes(pyCode);
      var CHUNK = 256;              // 每块原始字节数
      var chunks = splitBytes(bytes, CHUNK);
      var total = chunks.length || 1;

      /* ① 握手，进入 raw REPL */
      if (!await enterRaw()) {
        log('上传失败：未能进入 raw REPL。请按一下掌控板的复位键，' +
          '等屏幕出现「>>>」提示符后重试。', 'log-err');
        return false;
      }

      /* ② 在同一个会话里连续执行各条命令 */
      async function exec(cmd, t) {
        rx = '';
        await send(cmd);
        await sleep(50);
        await send('\x04');
        var head = await readBytes(2, t || 10000);
        if (head !== 'OK') {
          return {
            out: '', ok: false,
            err: '设备未确认接收命令（期望 "OK"，实际收到：' +
              JSON.stringify(head || '(空)') + '）'
          };
        }
        var o = await waitUntil('\x04', t || 10000);
        var e = await waitUntil('\x04', t || 10000);
        return { out: (o.text || '').trim(), err: (e.text || '').trim(), ok: true };
      }

      /* ③ 以二进制模式创建 main.py */
      var r0 = await exec('f = open("main.py", "wb")\nprint("__OPEN_OK__")\n', 8000);
      if (!r0.ok) { log('上传出错：' + r0.err, 'log-err'); await exitRaw(); return false; }
      if (r0.err) { log('上传出错：' + r0.err, 'log-err'); await exitRaw(); return false; }
      if (r0.out.indexOf('__OPEN_OK__') < 0) {
        log('上传可能失败，设备返回：' + (r0.out || '(空)'), 'log-err');
        await exitRaw();
        return false;
      }

      /* ④ 分块追加写内容（每块独立转义，转义序列不会跨块） */
      for (var i = 0; i < total; i++) {
        var piece = toPyBytesContent(chunks[i]);
        var r = await exec('f.write(b\'' + piece + '\')\n', 15000);
        if (!r.ok) { log('上传出错：' + r.err, 'log-err'); await exitRaw(); return false; }
        if (r.err) { log('上传出错：' + r.err, 'log-err'); await exitRaw(); return false; }
        if (i % 4 === 0 || i === total - 1) {
          log('  写入中… ' + Math.round((i + 1) / total * 100) + '%', 'log-hw');
        }
      }

      /* ⑤ 关闭文件并确认 */
      var r2 = await exec('f.close()\nprint("__UPLOAD_OK__")\n', 10000);
      if (!r2.ok) { log('上传出错：' + r2.err, 'log-err'); await exitRaw(); return false; }
      if (r2.err) { log('上传出错：' + r2.err, 'log-err'); await exitRaw(); return false; }
      if (r2.out.indexOf('__UPLOAD_OK__') < 0) {
        log('上传可能失败，设备返回：' + (r2.out || '(空)'), 'log-err');
        await exitRaw();
        return false;
      }
      log('main.py 写入成功（' + pyCode.length + ' 字节），正在重启运行…', 'log-ok');
      // 回友好 REPL 后 Ctrl-D 软复位 → 自动执行 main.py
      await exitRaw();
      await send('\x04');
      ZKB.toast && ZKB.toast('已上传，掌控板开始运行');
      return true;
    } catch (e) {
      log('上传异常：' + e.message, 'log-err');
      return false;
    } finally {
      cmdBusy = false;
    }
  }

  // REPL 临时运行（掉电丢失）
  async function runOnce(pyCode) {
    if (!port && !(await connect())) return false;
    log('通过 REPL 临时运行程序（重启后失效）…', 'log-hw');
    try {
      var r = await rawExec(pyCode, 60000);
      await exitRaw();
      if (!r.ok) { log('临时运行失败：' + r.err, 'log-err'); return false; }
      if (r.out) cleanLines(r.out).forEach(function (l) { log('[运行] ' + l, 'log-hw'); });
      if (r.err) log('运行报错：' + r.err, 'log-err');
      else log('程序执行结束。', 'log-ok');
      return !r.err;
    } catch (e) {
      log('运行异常：' + e.message, 'log-err');
      return false;
    }
  }

  ZKB.SerialLink = {
    isSupported: isSupported,
    isConnected: isConnected,
    connect: connect,
    disconnect: disconnect,
    uploadAndRun: uploadAndRun,
    runOnce: runOnce
  };

})(window);
