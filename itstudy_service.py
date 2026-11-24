"""
ITstudy Windows 服务包装器

将 Flask+Waitress 应用注册为 Windows 系统服务，
实现开机自启动、服务管理（启动/停止/重启）。
"""
import sys
import os
import logging

# 确保项目根目录在 sys.path 中。服务脚本部署在项目根目录或安装目录内。
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import servicemanager
import win32serviceutil
import win32service
import win32event


class ITstudyService(win32serviceutil.ServiceFramework):
    """ITstudy Windows 服务"""
    _svc_name_ = 'ITstudy'
    _svc_display_name_ = 'ITstudy 智慧教学平台'
    _svc_description_ = 'ITstudy 智慧教学平台 Web 服务（Flask + Waitress）'
    _svc_start_type_ = win32service.SERVICE_AUTO_START

    # ── 服务宿主 exe：显式用 venv 的 python.exe，不用 pywin32 的 pythonservice.exe ──
    # pywin32 的默认路径是 LocatePythonServiceExe()：它把
    # site-packages\win32\pythonservice.exe **搬进 sys.exec_prefix**——在 venv 里
    # 就是 venv 根目录。而该宿主是按「Python 安装目录」设计的（同目录要有
    # python3XX.dll、Lib\ 等），venv 根目录没有这些，服务启动必定失败：
    # `net start ITstudy` 报「服务没有响应控制功能」(2186)，事件日志只留一行
    # 无消息文本的 "Python Service" 错误，应用日志一行都没有——本机实测全新
    # 装机 100% 复现（历史上各次安装的服务从未真正启动过，数据库/日志全都
    # 没生成）。改为用 venv 的 python.exe 承载（Windows 服务经典做法）：
    # SCM 拉起「python.exe 脚本路径」，脚本 __main__ 的无参分支调用
    # StartServiceCtrlDispatcher，服务正常托管；同时不再产生
    # 「venv 根目录多一个 pythonservice.exe」这一副作用。
    _exe_name_ = sys.executable                      # venv\Scripts\python.exe
    _exe_args_ = '"%s"' % os.path.abspath(__file__)  # 本脚本绝对路径

    def __init__(self, args):
        win32serviceutil.ServiceFramework.__init__(self, args)
        self.hWaitStop = win32event.CreateEvent(None, 0, 0, None)
        self.logger = logging.getLogger('ITstudyService')
        self._server = None
        self._waitress = None

    def SvcStop(self):
        """服务停止：置停止事件，实际的服务器关闭由 SvcDoRun 侧执行。

        此前缺陷（两处叠加，服务只会卡在"正在停止"）：serve() 的返回值既
        未赋给 self._server，**serve() 本身也不返回 server 对象**——waitress
        3.x 源码里 `server.run()` 之后没有 return，整个调用要等服务器退出
        才返回 None。于是 SvcStop 里的 close() 恒为 no-op，asyncore 循环
        照常运行，SCM 等不到停止：`net stop ITstudy` 挂住、服务永远停在
        StopPending（实测 2026-09-13 全新装机，升级安装也随之失败）。
        现在 server 对象由 main() 用 create_server 拿到并持有，本方法只
        负责置事件唤醒 SvcDoRun 去关闭它。
        """
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        win32event.SetEvent(self.hWaitStop)

    def SvcDoRun(self):
        """服务运行"""
        servicemanager.LogMsg(
            servicemanager.EVENTLOG_INFORMATION_TYPE,
            servicemanager.PYS_SERVICE_STARTED,
            (self._svc_name_, '')
        )
        self.main()

    def main(self):
        """启动 Waitress 服务器：后台守护线程跑 run()，主线程等停止信号。

        不能直接在主线程调用 run()：它是阻塞的 asyncore 循环，停止信号
        到达时没有任何线程能执行关闭（这正是旧版服务停不下来的形态）。
        """
        try:
            import threading

            from app import create_app
            from waitress.server import create_server

            app = create_app()
            self.logger.info('ITstudy 服务启动中...')

            # 用 create_server 而非 serve()：serve() 只是
            # create_server + run() 的包装，且不返回 server 对象，拿不到
            # 句柄就无法在停止时关闭监听（见 SvcStop 注释）。注意 _quiet
            # 是 serve() 的私有参数，不在 waitress 调整项里，传给
            # create_server 会 ValueError。
            # connection_limit 2000 时挂起连接 × socket 缓冲最坏 140MB+，
            # 慢速/僵尸连接可占满 2000 而只有 W 线程服务；降到 400 与
            # 线程数（默认 48，可由 deploy.conf/管理端调整）匹配。
            # channel_timeout 300s 过长，恢复 120s 默认值。
            self._server = create_server(
                app,
                listen='0.0.0.0:5000',
                threads=app.config['WAITRESS_THREADS'],
                connection_limit=400,
                channel_timeout=120,
            )
            self._waitress = threading.Thread(
                target=self._server.run, name='waitress', daemon=True)
            self._waitress.start()

            # 等待停止信号。带 5s 超时轮询而非 INFINITE：run() 若在后台线程
            # 里抛异常（asyncore 循环内的任何错误），服务会变成"SCM 看着在跑、
            # 实际不服务"的僵尸——这里检测到线程已死就主动抛错，让 SCM 把
            # 服务标记为失败（恢复失败动作/告警随之生效）。
            while True:
                rc = win32event.WaitForSingleObject(self.hWaitStop, 5000)
                if rc == win32event.WAIT_OBJECT_0:
                    break
                if not self._waitress.is_alive():
                    raise RuntimeError('Waitress 服务线程意外退出')

            # 优雅关闭：close() 关闭监听套接字，asyncore 循环在在途连接散尽
            # 后退出。线程是守护线程——即便有连接卡到 channel_timeout（120s）
            # 也不阻塞进程退出，SCM 立即看到 STOPPED。
            try:
                self._server.close()
            except Exception:
                pass
            self._waitress.join(timeout=10)
            self._server = None
        except Exception as e:
            self.logger.error(f'ITstudy 服务异常: {e}')
            servicemanager.LogErrorMsg(f'ITstudy 服务异常: {e}')
            # 崩溃必须向上传播，让 SCM 感知服务已停止（此前缺陷：仅记日志
            # 导致 SCM 认为服务仍在运行，重启/升级被阻塞）
            raise


if __name__ == '__main__':
    if len(sys.argv) == 1:
        servicemanager.Initialize()
        servicemanager.PrepareToHostSingle(ITstudyService)
        servicemanager.StartServiceCtrlDispatcher()
    elif sys.argv[1] in ('-debug', '--debug') and len(sys.argv) > 2:
        # 上面 _exe_name_/_exe_args_ 让注册表 ImagePath 变成
        # 「python.exe 脚本路径」，而 pywin32 的 `debug` 子命令是把 ImagePath
        # 原样拼上 `-debug 服务名` 再 os.system —— 于是命令行成了
        # 「python.exe 脚本.py -debug ITstudy」，HandleCommandLine 认不出首个
        # 参数（会打印 usage）。这里接住该形态，使 `python itstudy_service.py
        # debug` 依旧可用（等价于 pywin32 内部的 DebugService）。
        win32serviceutil.DebugService(ITstudyService, sys.argv[2:])
    else:
        win32serviceutil.HandleCommandLine(ITstudyService)
