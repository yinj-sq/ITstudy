# -*- coding: utf-8 -*-
"""大文件附件下载专用线程池。

Waitress 一线程一连接：一次 200MB 附件的磁盘直送会在整个传输期间占用一个
工作线程。并发下载一多，其余页面/API/心跳请求就没有线程可用。本模块为
**大文件附件下载**提供独立的有界通道：

- 仅当 ``as_attachment=True`` 且文件达到 ``large_download_threshold_mb``
  （默认 16MB）时进入；内联预览与视频 Range 流保持原 ``send_file`` 路径，
  不受名额限制；
- 并发名额（``large_download_pool_size``，默认 8）用尽时立即返回 503 +
  ``Retry-After``，不排队、不占用 Waitress 线程等待，其余请求仍可服务；
- 文件块读取提交到专用 ThreadPoolExecutor，避免下载 I/O 与业务线程争用；
  文件句柄在发送完成或客户端断开时关闭，同时归还名额。

任一配置为 0 即完全退回原 ``send_file`` 路径。
"""
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from zlib import adler32

_executor = None
_slots = None
_lock = threading.Lock()


def _config_int(name, default):
    try:
        from flask import current_app
        return max(0, int(current_app.config.get(name, default)))
    except Exception:
        return default


def _pool():
    """惰性创建专用线程池与名额信号量（首次大文件下载时初始化）。"""
    global _executor, _slots
    if _executor is not None:
        return _executor, _slots
    with _lock:
        if _executor is None:
            size = max(1, _config_int('LARGE_DOWNLOAD_POOL_SIZE', 8))
            _executor = ThreadPoolExecutor(
                max_workers=size, thread_name_prefix='itstudy-download')
            _slots = threading.BoundedSemaphore(size)
    return _executor, _slots


class _PooledReader:
    """把 ``read`` 提交到下载线程池的文件包装器。

    接口满足 werkzeug/waitress 文件包装器的需要（read/seek/tell/seekable/
    close/fileno）；``close`` 幂等，并在关闭底层文件后归还下载名额。
    """

    def __init__(self, fileobj, executor, on_close=None):
        self._file = fileobj
        self._executor = executor
        self._on_close = on_close
        self._close_lock = threading.Lock()
        self._closed = False

    def read(self, size=-1):
        try:
            return self._executor.submit(self._file.read, size).result()
        except RuntimeError:
            # 解释器关闭阶段线程池已不可用：退回同步读取（尽力完成本次传输）
            return self._file.read(size)

    def seekable(self):
        return self._file.seekable()

    def seek(self, *args):
        return self._file.seek(*args)

    def tell(self):
        return self._file.tell()

    def fileno(self):
        return self._file.fileno()

    def close(self):
        with self._close_lock:
            if self._closed:
                return
            self._closed = True
        try:
            self._file.close()
        finally:
            if self._on_close is not None:
                self._on_close()


def send_large_download(abs_path, **send_file_kwargs):
    """``send_file`` 的大文件附件版本。

    参数与 ``flask.send_file`` 一致。非附件、低于阈值或功能关闭时行为与
    ``send_file`` 完全相同；附件达到阈值时占用一个下载名额并走专用线程池。
    名额耗尽返回 503（带 Retry-After），由调用方原样返回给客户端。
    """
    from flask import Response, current_app, request, send_file

    pool_size = _config_int('LARGE_DOWNLOAD_POOL_SIZE', 8)
    threshold_mb = _config_int('LARGE_DOWNLOAD_THRESHOLD_MB', 16)
    as_attachment = bool(send_file_kwargs.get('as_attachment'))
    try:
        size = os.path.getsize(abs_path)
    except OSError:
        return send_file(abs_path, **send_file_kwargs)

    if (not as_attachment or pool_size <= 0 or threshold_mb <= 0
            or size < threshold_mb * 1024 * 1024):
        return send_file(abs_path, **send_file_kwargs)

    executor, slots = _pool()
    if not slots.acquire(blocking=False):
        current_app.logger.warning(
            '大文件下载并发名额已满，快速拒绝: %s', abs_path)
        response = Response('当前下载任务较多，请稍后重试。', status=503,
                            mimetype='text/plain')
        response.headers['Retry-After'] = '5'
        return response

    try:
        fileobj = open(abs_path, 'rb')
    except OSError:
        # 竞态删除/权限变化：退回 send_file 以保持 404/500 语义一致
        slots.release()
        return send_file(abs_path, **send_file_kwargs)

    reader = _PooledReader(fileobj, executor, on_close=slots.release)
    try:
        kwargs = dict(send_file_kwargs)
        kwargs.setdefault('download_name', os.path.basename(abs_path))
        mtime = os.path.getmtime(abs_path)
        kwargs.setdefault('last_modified', mtime)
        # 与路径模式的 send_file 一致：支持 If-None-Match 304 与断点续传
        kwargs.setdefault(
            'etag', f'{mtime}-{size}-{adler32(abs_path.encode()) & 0xFFFFFFFF}')
        # 文件对象拿不到 path 元数据：先非条件发送，再按已知大小补 Range/304
        kwargs['conditional'] = False
        response = send_file(reader, **kwargs)
        response.content_length = size
        return response.make_conditional(
            request.environ, accept_ranges=True, complete_length=size)
    except Exception:
        reader.close()
        raise
