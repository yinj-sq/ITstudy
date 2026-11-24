import os
import shutil

from sqlalchemy import func

from app.extensions import db
from app.models import Student, StudentDriveFile
from app.utils import save_file_to_disk, read_file_from_disk, delete_file_from_disk


ALLOWED_DRIVE_EXTENSIONS = {
    'pdf', 'png', 'jpg', 'jpeg', 'gif', 'bmp', 'webp',
    'mp3', 'wav', 'ogg', 'mp4', 'webm', 'avi',
    'txt', 'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx',
    'zip', 'rar', '7z', 'py', 'js', 'html', 'htm', 'css', 'json', 'xml', 'md', 'csv'
}
MAX_DRIVE_FILE_SIZE_MB = 200
# 全局默认网盘容量（MB）：初始配额收紧为 20MB，防止批量导入学生后
# 大量文件上传撑爆存储；容量可由管理端按学生/班级/全局调整
DEFAULT_STUDENT_DRIVE_QUOTA_MB = 20


def get_preview_type(filename):
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
    if ext in ('png', 'jpg', 'jpeg', 'gif', 'bmp', 'webp'):
        return 'image'
    if ext == 'pdf':
        return 'pdf'
    if ext in ('mp3', 'wav', 'ogg'):
        return 'audio'
    if ext in ('mp4', 'webm', 'avi'):
        return 'video'
    if ext in ('txt', 'py', 'js', 'html', 'htm', 'css', 'json', 'xml', 'md', 'csv'):
        return 'text'
    return ''


def validate_drive_filename(filename):
    if not filename or '.' not in filename:
        return False, '文件缺少扩展名'
    ext = filename.rsplit('.', 1)[-1].lower()
    if ext not in ALLOWED_DRIVE_EXTENSIONS:
        return False, f'不支持的文件类型: .{ext}'
    return True, ''


def get_student_drive_used(student_id):
    return db.session.query(func.coalesce(func.sum(StudentDriveFile.file_size), 0)).filter(
        StudentDriveFile.student_id == student_id
    ).scalar() or 0


def get_student_drive_quota(student_id=None):
    """解析学生网盘容量（MB → bytes）。

    优先级：学生级覆盖（student_drive_quota.student_id）
            → 班级级覆盖（student_drive_quota.class_id）
            → 全局默认（SystemConfig: drive_default_quota_mb，默认 1024）
    """
    from app.models import StudentDriveQuota, SystemConfig, Student as _Student
    if student_id:
        q = StudentDriveQuota.query.filter_by(student_id=student_id).first()
        if q:
            return q.quota_mb * 1024 * 1024
        stu = db.session.get(_Student, student_id)
        if stu and stu.class_id:
            cq = StudentDriveQuota.query.filter_by(class_id=stu.class_id).first()
            if cq:
                return cq.quota_mb * 1024 * 1024
    default_mb = SystemConfig.get('drive_default_quota_mb', str(DEFAULT_STUDENT_DRIVE_QUOTA_MB))
    try:
        default_mb = int(default_mb)
    except (TypeError, ValueError):
        default_mb = DEFAULT_STUDENT_DRIVE_QUOTA_MB
    if default_mb < 1:
        default_mb = DEFAULT_STUDENT_DRIVE_QUOTA_MB
    return default_mb * 1024 * 1024


def get_drive_quota_mb_display(student_id=None):
    """获取配额（MB 整数，用于界面展示）"""
    return get_student_drive_quota(student_id) // (1024 * 1024)


def set_drive_quota_mb(target, quota_mb, target_type='student'):
    """设置网盘容量覆盖（target_type: 'student' / 'class' / 'global'）。

    - student/class：写入或更新 student_drive_quota 覆盖记录
    - global：写入 SystemConfig.drive_default_quota_mb
    quota_mb 必须 >= 1；target_type=student 时 target 为学生 id，class 同理。
    """
    from app.models import StudentDriveQuota, SystemConfig
    quota_mb = int(quota_mb)
    if quota_mb < 1:
        raise ValueError('容量必须大于 0 MB')
    if target_type == 'global':
        SystemConfig.set('drive_default_quota_mb', str(quota_mb))
        db.session.commit()
        return quota_mb
    if target_type == 'student':
        row = StudentDriveQuota.query.filter_by(student_id=target).first()
        if row:
            row.quota_mb = quota_mb
        else:
            db.session.add(StudentDriveQuota(student_id=target, quota_mb=quota_mb))
    elif target_type == 'class':
        row = StudentDriveQuota.query.filter_by(class_id=target).first()
        if row:
            row.quota_mb = quota_mb
        else:
            db.session.add(StudentDriveQuota(class_id=target, quota_mb=quota_mb))
    else:
        raise ValueError('无效的容量设置类型')
    db.session.commit()
    return quota_mb


def set_drive_quota_mb_bulk(student_ids, quota_mb):
    """批量设置学生网盘容量：一次 IN 查询 + 单次提交。

    逐生调用 set_drive_quota_mb 时每生 1 次 SELECT + 1 次 COMMIT（含 fsync），
    勾选整年级 ~1200 人 ≈ 2400 次往返且全程占用一个 Waitress 线程；
    此处合并为 1 次查询 + 1 次提交。返回生效人数。
    """
    from app.models import StudentDriveQuota
    quota_mb = int(quota_mb)
    if quota_mb < 1:
        raise ValueError('容量必须大于 0 MB')
    ids = list(dict.fromkeys(int(i) for i in student_ids))
    if not ids:
        return 0
    existing = {
        row.student_id: row for row in StudentDriveQuota.query.filter(
            StudentDriveQuota.student_id.in_(ids)).all()
    }
    for sid in ids:
        row = existing.get(sid)
        if row:
            row.quota_mb = quota_mb
        else:
            db.session.add(StudentDriveQuota(student_id=sid, quota_mb=quota_mb))
    db.session.commit()
    return len(ids)


def clear_drive_quota_override(target, target_type='student'):
    """清除容量覆盖，恢复全局默认（target_type: 'student' / 'class'）"""
    from app.models import StudentDriveQuota
    if target_type == 'student':
        row = StudentDriveQuota.query.filter_by(student_id=target).first()
    elif target_type == 'class':
        row = StudentDriveQuota.query.filter_by(class_id=target).first()
    else:
        raise ValueError('无效的容量清除类型')
    if row:
        db.session.delete(row)
        db.session.commit()
    return True


def read_drive_file(file_record):
    return read_file_from_disk(file_record.file_path)


def _drive_usage_with_preload(student_id, preload):
    """批量投递场景的配额判定：预加载映射优先，缺失时实时查询。

    调用方保证学生行已加锁（SELECT FOR UPDATE），因此锁后重算的 used
    是事务内一致值。返回 (used, quota)（bytes）。
    """
    if preload is None:
        return get_student_drive_used(student_id), get_student_drive_quota(student_id)
    used_map = preload['used_map']
    if student_id not in used_map:
        # 惰性初始化：锁行后实时求和（每学生仅一次，替代每文件一次）
        used_map[student_id] = get_student_drive_used(student_id)
    used = used_map[student_id]
    quota = preload['quota_map'].get(student_id, preload['default_quota'])
    return used, quota


class _FileStorageLike:
    """把普通文件对象伪装成 werkzeug FileStorage（仅流式保存所需接口）。

    作业投递场景：附件逐学生 open 一次文件，用该适配器走
    save_stream_to_disk 流式落盘，避免整文件驻留内存。
    """

    def __init__(self, f):
        self.stream = f

    def save(self, dst, buffer_size=65536):
        src = self.stream
        src.seek(0)
        with open(dst, 'wb') as out:
            shutil.copyfileobj(src, out, buffer_size)
        src.seek(0)


def _discard_orphan(rel_path):
    """回收已落盘但 DB 记录未提交成功的网盘文件（尽力而为）。

    投递为逐条提交：commit 失败回滚时文件已写出，若不回收则成为
    无记录引用的磁盘孤儿（配额统计按 DB 行计算，孤儿只占磁盘不占配额）。
    """
    if not rel_path:
        return
    try:
        from app.utils import delete_file_from_disk
        delete_file_from_disk(rel_path)
    except Exception:
        import logging
        logging.getLogger(__name__).warning(
            '投递失败后回收网盘文件失败: %s', rel_path, exc_info=True)


def save_drive_file_for_student(student_id, file_content, original_filename,
                                sender_type='teacher', sender_id=None, sender_name='',
                                source_type='manual', source_id=None, note=None,
                                commit=False, file_storage=None, _preload=None):
    """保存学生网盘文件。file_storage 提供时走流式落盘（save 直写磁盘，
    不整文件读入内存；大小/魔数/配额校验逻辑与内存路径一致）。

    _preload（批量投递场景）：{'quota_map': {student_id: bytes},
    'default_quota': bytes, 'used_map': {student_id: bytes}}。
    配额映射由调用方一次预加载（避免每文件 2-3 次 DB 往返）；
    used_map 惰性初始化——首次遇到某学生时在行锁后重算并缓存，
    保证 READ COMMITTED 下锁后配额判定一致。**调用方必须在 commit
    成功后自行累加 used_map**（失败回滚不得计入配额）。
    """
    ok, message = validate_drive_filename(original_filename)
    if not ok:
        raise ValueError(message)
    if file_storage is not None:
        # 流式路径：文件头魔数校验（webp 魔数需前 12 字节，见
        # validate_image_magic_head）+ 大小校验
        from app.utils import validate_image_magic_head as _vimh
        if not _vimh(file_storage, original_filename):
            raise ValueError('图片内容校验失败（文件头与扩展名不匹配）')
        file_storage.stream.seek(0, 2)
        file_size = file_storage.stream.tell()
        file_storage.stream.seek(0)
        if file_size <= 0:
            raise ValueError('文件为空')
        if file_size > MAX_DRIVE_FILE_SIZE_MB * 1024 * 1024:
            raise ValueError(f'单个文件不能超过 {MAX_DRIVE_FILE_SIZE_MB}MB')
        locked = Student.query.filter(Student.id == student_id).with_for_update().first()
        if not locked:
            raise ValueError('学生不存在')
        used, quota = _drive_usage_with_preload(student_id, _preload)
        if used + file_size > quota:
            # 提示用实际生效配额（学生/班级覆盖可能远大于默认值，
            # 固定提示默认 20MB 会误导排障）
            raise ValueError(f'学生网盘空间不足（上限 {quota // (1024 * 1024)}MB）')
        from app.utils import save_stream_to_disk as _ss
        ok_save, msg, rel_path, size = _ss(
            file_storage, f'cloud_drive/{student_id}', original_filename,
            max_bytes=MAX_DRIVE_FILE_SIZE_MB * 1024 * 1024)
        if not ok_save:
            raise ValueError(msg)
        file_size = size
    else:
        if isinstance(file_content, str):
            file_content = file_content.encode('utf-8')
        file_size = len(file_content or b'')
        if file_size <= 0:
            raise ValueError('文件为空')
        # 图片魔数校验：伪装成图片的可执行内容拒绝入库
        from app.utils import validate_image_magic
        if not validate_image_magic(file_content, original_filename):
            raise ValueError('图片内容校验失败（文件头与扩展名不匹配）')
        if file_size > MAX_DRIVE_FILE_SIZE_MB * 1024 * 1024:
            raise ValueError(f'单个文件不能超过 {MAX_DRIVE_FILE_SIZE_MB}MB')
        # 锁定学生行串行化配额检查（SELECT FOR UPDATE），
        # 防止并发上传同时通过检查导致配额超额（TOCTOU）
        locked = Student.query.filter(Student.id == student_id).with_for_update().first()
        if not locked:
            raise ValueError('学生不存在')
        used, quota = _drive_usage_with_preload(student_id, _preload)
        if used + file_size > quota:
            raise ValueError(f'学生网盘空间不足（上限 {quota // (1024 * 1024)}MB）')
        rel_path = save_file_to_disk(file_content, f'cloud_drive/{student_id}', original_filename)
    # 批量投递预加载的 used_map 由调用方在 commit 成功后累加：
    # 此前在落盘成功后、commit 前累加，提交失败回滚后配额仍被计入，
    # 导致后续附件误报空间不足。
    record = StudentDriveFile(
        student_id=student_id,
        sender_type=sender_type,
        sender_id=sender_id,
        sender_name=sender_name or '',
        filename=os.path.basename(rel_path),
        original_filename=original_filename,
        file_size=file_size,
        file_path=rel_path,
        source_type=source_type,
        source_id=source_id,
        note=note,
    )
    db.session.add(record)
    if commit:
        db.session.commit()
    return rel_path


def delete_drive_file(record, commit=False):
    """删除网盘记录与磁盘文件。

    commit=True 时先提交数据库、成功后再删盘：此前先删盘后提交，提交失败
    （连接中断/死锁）回滚后记录仍在而文件已 404，且配额仍计入。
    """
    path = record.file_path
    db.session.delete(record)
    if commit:
        db.session.commit()
        delete_file_from_disk(path)
    else:
        # 无 commit 的调用方自行负责提交；保持旧语义（先删盘）仅在提交
        # 成功路径可接受，当前仓库无此调用方
        delete_file_from_disk(path)


def find_idle_drive_files(idle_days):
    """查询闲置 N 天未活动的个人网盘文件（供自动清理与预览清单）。

    返回 [(StudentDriveFile, Student), ...] 列表，按闲置时间降序。
    闲置判定：文件上传时间（created_at）早于 now - idle_days。
    仅清理学生本人上传的文件（source_type='student_upload'）：教师/系统
    投递的数据（作业附件 homework、活动资料 activity、手动发送 manual）
    不跟踪访问活动，按上传时间判"闲置"会误删学生尚未查看的教学资料。
    """
    from datetime import datetime as _dt, timedelta as _td
    from app.models import Student as _Student
    cutoff = _dt.now() - _td(days=idle_days)
    rows = StudentDriveFile.query.filter(
        StudentDriveFile.created_at < cutoff,
        StudentDriveFile.source_type == 'student_upload'
    ).order_by(StudentDriveFile.created_at.asc()).all()
    student_ids = {r.student_id for r in rows}
    students = {}
    if student_ids:
        students = {s.id: s for s in
                    _Student.query.filter(_Student.id.in_(student_ids)).all()}
    return [(r, students.get(r.student_id)) for r in rows]


def cleanup_idle_drive_files(idle_days, log_action='自动清理闲置网盘文件'):
    """删除闲置 N 天未活动的个人网盘文件（磁盘 + 数据库 + 操作日志）。

    返回删除的文件数；失败的文件跳过并记录，不中断批量清理。
    """
    from app.models import Log as _Log
    from datetime import datetime as _dt
    rows = find_idle_drive_files(idle_days)
    deleted = 0
    failed = 0
    freed_bytes = 0
    paths = []
    # 先一次性提交数据库删除，成功后再清盘：此前逐条先删盘、循环完才
    # commit，任一提交失败会让整批记录回滚而磁盘文件已全部删除。
    for record, student in rows:
        freed_bytes += record.file_size or 0
        paths.append(record.file_path)
        db.session.delete(record)
        deleted += 1
    if deleted:
        db.session.add(_Log(
            user_id=0, user_type='admin', action=log_action,
            detail=(f'闲置{idle_days}天：删除 {deleted} 个文件'
                    f'（释放 {freed_bytes // (1024 * 1024)}MB）'),
            time=_dt.now()))
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        import logging
        logging.getLogger(__name__).warning(
            '批量清理网盘记录提交失败，已回滚且未删除任何磁盘文件',
            exc_info=True)
        return {'deleted': 0, 'failed': len(rows),
                'freed_mb': 0}
    for path in paths:
        try:
            delete_file_from_disk(path)
        except Exception:
            failed += 1
            import logging
            logging.getLogger(__name__).warning(
                '清理网盘文件失败（记录已删除，磁盘残留）: %s', path,
                exc_info=True)
    return {'deleted': deleted, 'failed': failed,
            'freed_mb': freed_bytes // (1024 * 1024)}


def get_cleanup_config():
    """读取网盘自动清理配置：{enabled, idle_days, interval_hours}"""
    from app.models import SystemConfig
    # 数值钳制：DB 值被脚本/手工改为 0 或负数时 cutoff=now 会删除全部
    # 个人网盘文件（set 接口有校验，但直接改库不经过它）
    return {
        'enabled': SystemConfig.get_bool('drive_cleanup_enabled', False),
        'idle_days': max(1, int(SystemConfig.get('drive_cleanup_idle_days', '90') or 90)),
        'interval_hours': max(1, int(SystemConfig.get('drive_cleanup_interval_hours', '24') or 24)),
    }


def set_cleanup_config(enabled, idle_days, interval_hours):
    """保存网盘自动清理配置（数值范围校验）"""
    from app.models import SystemConfig
    idle_days = int(idle_days)
    interval_hours = int(interval_hours)
    if idle_days < 1:
        raise ValueError('闲置天数必须大于 0')
    if interval_hours < 1:
        raise ValueError('检查周期必须大于 0 小时')
    SystemConfig.set('drive_cleanup_enabled', 'true' if enabled else 'false')
    SystemConfig.set('drive_cleanup_idle_days', str(idle_days))
    SystemConfig.set('drive_cleanup_interval_hours', str(interval_hours))
    db.session.commit()
    return get_cleanup_config()


def deliver_homework_attachments(homework, homework_dir, sender_name='教师',
                                 progress=None):
    """把作业附件复制到所有接收班级学生的个人网盘，按作业和文件名幂等去重。

    两阶段投递：先收集全部投递计划，再执行写盘+写库。
    容错策略：单个学生投递失败（容量不足/文件超限等）不再整体回滚——
    跳过该学生并记录原因，其余学生继续投递；已写盘文件不清理（投递成功
    部分保留，避免 342 名学生中 1 个容量不足导致全班都没收到附件）。
    写库为逐条提交：每份投递成功即 commit，单条 commit 失败只回滚该条，
    与「投递成功部分保留」语义一致（整批一次 commit 时，末次失败会
    把全部已投递记录回滚、磁盘文件却已写出的孤儿）。

    Args:
        homework: Homework 实例
        homework_dir: 作业附件目录
        sender_name: 投递者显示名
        progress: 可选回调 progress(done, total)，用于后台任务上报进度

    Returns:
        dict: {'delivered': 投递成功数, 'total': 计划总数,
               'insufficient': [{'student': 姓名, 'class': 班级}],  容量不足
               'failed': [{'student': 姓名, 'class': 班级, 'reason': 原因}]}
    """
    import json

    result = {'delivered': 0, 'total': 0,
              'insufficient': [], 'failed': []}
    if not homework.attachments:
        return result
    try:
        attachments = json.loads(homework.attachments)
    except Exception:
        attachments = []
    if not attachments:
        return result

    class_ids = [c.id for c in homework.classes.all()]
    if not class_ids:
        return result
    students = Student.query.filter(Student.class_id.in_(class_ids)).all()
    if not students:
        return result

    root = os.path.realpath(homework_dir)
    # 阶段一：收集投递计划（跳过已存在的记录，幂等去重）
    # 性能：此前按 (学生 × 附件) 逐条 filter_by 查询（342 学生 × 3 附件
    # ≈ 1000+ 次 DB 往返），改为一次 IN 批量加载已投递集合
    student_ids = [s.id for s in students]
    existing_set = set()
    if student_ids:
        existing_rows = StudentDriveFile.query.filter(
            StudentDriveFile.student_id.in_(student_ids),
            StudentDriveFile.source_type == 'homework',
            StudentDriveFile.source_id == homework.id
        ).with_entities(
            StudentDriveFile.student_id,
            StudentDriveFile.original_filename
        ).all()
        existing_set = {(r[0], r[1]) for r in existing_rows}
    # 按附件分组：[(safe_name, file_path, [student, ...])]——每附件只 open
    # 一次流式读取投递全部目标学生，内容不驻留内存
    plan = []
    for filename in attachments:
        safe_name = (filename or '').replace('\\', '/').lstrip('/')
        if not safe_name or '..' in safe_name.split('/'):
            continue
        file_path = os.path.realpath(os.path.join(root, safe_name))
        if file_path == root or not file_path.startswith(root + os.sep) or not os.path.isfile(file_path):
            continue
        targets = [s for s in students if (s.id, safe_name) not in existing_set]
        if targets:
            plan.append((safe_name, file_path, targets))
    if not plan:
        return result
    result['total'] = sum(len(t) for _, _, t in plan)

    # 阶段二：逐个容错执行（容量不足/单文件超限跳过并记录，不中断整体）
    # 配额映射一次预加载（学生/班级覆盖行 + 全局默认），替代每文件
    # 2-3 次往返；used_map 在行锁后惰性初始化（每学生一次 SUM）。
    from app.models import StudentDriveQuota, SystemConfig
    quota_map = {}
    if student_ids:
        quota_rows = StudentDriveQuota.query.filter(
            db.or_(
                StudentDriveQuota.student_id.in_(student_ids),
                StudentDriveQuota.class_id.in_(class_ids)
            )
        ).all()
        quota_map = {r.student_id: r.quota_mb * 1024 * 1024 for r in quota_rows if r.student_id}
        # 班级级覆盖：<class_id> 键（get_student_drive_quota 语义一致）
        class_quota = {r.class_id: r.quota_mb * 1024 * 1024
                       for r in quota_rows if r.class_id}
        for stu in students:
            if stu.id not in quota_map and stu.class_id in class_quota:
                quota_map[stu.id] = class_quota[stu.class_id]
    default_quota = SystemConfig.get(
        'drive_default_quota_mb', str(DEFAULT_STUDENT_DRIVE_QUOTA_MB))
    try:
        default_quota = int(default_quota)
    except (TypeError, ValueError):
        default_quota = DEFAULT_STUDENT_DRIVE_QUOTA_MB
    if default_quota < 1:
        default_quota = DEFAULT_STUDENT_DRIVE_QUOTA_MB
    default_quota = default_quota * 1024 * 1024
    preload = {'quota_map': quota_map, 'default_quota': default_quota, 'used_map': {}}

    done = 0
    for safe_name, file_path, targets in plan:
        # 源文件大小在本附件内固定；commit 成功后才计入 used_map
        try:
            attachment_size = os.path.getsize(file_path)
        except OSError:
            attachment_size = 0
        with open(file_path, 'rb') as _f:
            stream = _FileStorageLike(_f)
            for student in targets:
                # 姓名提前取值：commit 后 ORM 对象过期，异常路径再访问会触发
                # 额外 SELECT（会话异常时甚至拿不到值）
                sname = student.name
                sclass = student.student_class or ''
                rel = None
                try:
                    rel = save_drive_file_for_student(
                        student.id, None, safe_name,
                        sender_type='teacher',
                        sender_name=sender_name,
                        source_type='homework',
                        source_id=homework.id,
                        note=f'作业附件：{homework.title}',
                        commit=False,
                        file_storage=stream,
                        _preload=preload
                    )
                    # 逐条提交：单条失败只回滚本条，已投递的记录/文件保持
                    # 一致（此前整批最后一次 commit，失败时 DB 全回滚而磁盘
                    # 文件已写 → 孤儿文件 + 结果误报成功）
                    db.session.commit()
                    # commit 成功后才累加；失败分支不污染 used_map
                    if student.id in preload['used_map']:
                        preload['used_map'][student.id] += attachment_size
                    result['delivered'] += 1
                except ValueError as exc:
                    db.session.rollback()
                    _discard_orphan(rel)
                    reason = str(exc)
                    info = {'student': sname,
                            'class': sclass}
                    if '空间不足' in reason or '容量' in reason:
                        info['quota_mb'] = preload['quota_map'].get(
                            student.id, default_quota) // (1024 * 1024)
                        result['insufficient'].append(info)
                    else:
                        info['reason'] = reason
                        result['failed'].append(info)
                except Exception:
                    # commit 失败等异常：文件已写而记录回滚，回收磁盘文件
                    db.session.rollback()
                    _discard_orphan(rel)
                    result['failed'].append({
                        'student': sname,
                        'class': sclass,
                        'reason': '投递异常',
                    })
                done += 1
                if progress:
                    progress(done, result['total'])
    return result
