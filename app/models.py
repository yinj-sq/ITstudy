"""ITstudy 数据模型 — 版权所有 (C) 2025-2026 YINJUN"""
import json
import os
import re
import hashlib
import secrets
import uuid
from datetime import datetime
from flask import current_app
from sqlalchemy import text
from werkzeug.security import generate_password_hash, check_password_hash
from app.extensions import db
from app.credential_crypto import decrypt_secret, encrypt_secret, is_encrypted_secret


# 选项前缀可识别的分隔符集合: . : 、 ) ） ] 】 - 空格 , ; 。（全角变体会先折叠）
_OPTION_SEPARATORS = '.:、)）]】- ,;。'
_SQL_IDENTIFIER_RE = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')


def _quote_sql_identifier(identifier):
    """Quote a trusted SQL identifier after strict validation."""
    if not _SQL_IDENTIFIER_RE.fullmatch(str(identifier or '')):
        raise ValueError(f'非法 SQL 标识符: {identifier!r}')
    return f'"{identifier}"'


def _fold_fullwidth_ascii(value):
    """全角 ASCII（字母/数字/标点）→ 半角，供选项前缀识别使用。"""
    return ''.join(
        chr(ord(c) - 0xFEE0) if '\uFF01' <= c <= '\uFF5E' else c
        for c in str(value or '')
    )


def normalize_options(options_str):
    """标准化选项格式并排序

    1. 识别各种前缀格式（A./A:/A、/A)/A-/A /（A）等），统一为A.格式
    2. 全角字母/句点/冒号/括号按半角识别（中文输入法常见）
    3. 纯字母/空格/逗号分隔的 ABCD 视为选项标签（输出 A.|B.|C.|D.）
    4. 按字母前缀排序；无前缀时自动补齐A. B. C. D. ...
    """
    if not options_str:
        return options_str
    text = _fold_fullwidth_ascii(options_str)
    # 无竖线但为纯字母标签序列（A B C D / A,B,C,D / A、B、C、D）：
    # 这些写法在导入模板里很常见，按选项标签拆分而不是当成一条选项。
    if '|' not in text and re.fullmatch(
            r'\s*[A-Za-z](?:\s*[,，、;；]\s*[A-Za-z]|\s+[A-Za-z])*\s*', text):
        text = re.sub(r'[,，、;；]', ' ', text)
        parts = text.split()
    else:
        parts = [o.strip() for o in text.split('|') if o.strip()]
    if not parts:
        return options_str

    # 前缀：字母 + 分隔符；或中文/英文括号包裹的字母
    prefix_re = re.compile(r'^([A-Za-z])\s*[' + re.escape(_OPTION_SEPARATORS) + r']\s*')
    paren_re = re.compile(r'^[（(]\s*([A-Za-z])\s*[）)]\s*')

    extracted = []  # list of (prefix_letter, content) or None if no prefix
    for opt in parts:
        opt = opt.strip()
        if re.fullmatch(r'[A-Za-z]', opt):
            # 裸字母（如导入的 A|B|C|D）按“带标签、空内容”处理，
            # 避免归一成 A.A / B.B 这类重复文本
            extracted.append((opt.upper(), ''))
            continue
        m = paren_re.match(opt) or prefix_re.match(opt)
        if m:
            letter = m.group(1).upper()
            content = opt[m.end():].strip()
            # 仅剥离与外侧同字母的重复前缀层（修复 A.A.xxx / （A）A.xxx），
            # 不吞掉内容本身以字母开头的文本（如 A.B.C 的 B.C）
            while True:
                m2 = paren_re.match(content) or prefix_re.match(content)
                if m2 and m2.group(1).upper() == letter:
                    content = content[m2.end():].strip()
                else:
                    break
            extracted.append((letter, content))
        else:
            extracted.append(None)

    prefix_count = sum(1 for e in extracted if e is not None)

    if prefix_count == len(parts):
        # 全部带前缀：去重（同一字母前缀只保留首个）后规范化分隔符为. 并排序
        seen = set()
        unique = []
        for letter, content in extracted:
            if letter in seen:
                continue
            seen.add(letter)
            unique.append((letter, content))
        unique.sort(key=lambda x: x[0])
        return '|'.join(f"{letter}.{content}" for letter, content in unique)
    else:
        # 无前缀或混合：剥离已有前缀后统一分配A. B. C. D. ...
        if len(parts) > 26:
            # chr(65+i) 在 i>=26 时会产生 [ \ ] 等非法前缀，直接返回原串
            return options_str
        result = []
        for i, opt in enumerate(parts):
            ex = extracted[i]
            content = ex[1] if ex else opt
            result.append(f"{chr(65 + i)}.{content}")
        return '|'.join(result)


class Class(db.Model):
    """班级表"""
    __tablename__ = 'classes'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False, index=True)
    description = db.Column(db.String(200))
    create_time = db.Column(db.DateTime, default=datetime.now)

    students = db.relationship('Student', backref='class_', lazy=True)
    groups = db.relationship('StudyGroup', backref='class_', lazy=True,
                             cascade='all, delete-orphan')


class StudyGroup(db.Model):
    """学习小组表"""
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(10), nullable=False)
    slogan = db.Column(db.String(100))
    icon = db.Column(db.String(50))
    class_id = db.Column(db.Integer, db.ForeignKey('classes.id'), nullable=False)
    leader_id = db.Column(db.Integer, db.ForeignKey('student.id'), nullable=True, index=True)
    drive_enabled = db.Column(db.Boolean, default=True)
    upload_enabled = db.Column(db.Boolean, default=True)
    max_space_mb = db.Column(db.Integer, default=50)
    create_time = db.Column(db.DateTime, default=datetime.now)

    leader = db.relationship('Student', foreign_keys=[leader_id])
    members = db.relationship('Student', backref='group', lazy=True,
                              foreign_keys='Student.group_id')
    files = db.relationship('GroupFile', backref='group', lazy=True,
                            cascade='all, delete-orphan')


class GroupFile(db.Model):
    """小组共享网盘文件"""
    __tablename__ = 'group_file'

    id = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey('study_group.id'), nullable=False)
    uploader_id = db.Column(db.Integer, db.ForeignKey('student.id'), nullable=False, index=True)
    filename = db.Column(db.String(255), nullable=False)
    original_filename = db.Column(db.String(255), nullable=False)
    file_size = db.Column(db.Integer, default=0)
    file_path = db.Column(db.String(500), nullable=False)  # 磁盘相对路径（相对 UPLOAD_FOLDER）
    pptist_json = db.Column(db.Text, nullable=True)  # PPTist 兼容 JSON（仅 PPTX 文件，上传时自动生成）
    upload_time = db.Column(db.DateTime, default=datetime.now)

    uploader = db.relationship('Student', foreign_keys=[uploader_id])

    def get_absolute_path(self, upload_folder):
        """返回文件的绝对路径"""
        import os
        return os.path.join(upload_folder, self.file_path) if self.file_path else None

    def read_content(self, upload_folder):
        """读取文件内容（二进制）"""
        abs_path = self.get_absolute_path(upload_folder)
        if abs_path and os.path.exists(abs_path):
            with open(abs_path, 'rb') as f:
                return f.read()
        return None


class StudentDriveFile(db.Model):
    """单个学生个人网盘文件"""
    __tablename__ = 'student_drive_file'

    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('student.id'), nullable=False, index=True)
    sender_type = db.Column(db.String(20), default='teacher', index=True)  # teacher/admin/student/system
    sender_id = db.Column(db.Integer, nullable=True)
    sender_name = db.Column(db.String(80))
    filename = db.Column(db.String(255), nullable=False)
    original_filename = db.Column(db.String(255), nullable=False)
    file_size = db.Column(db.Integer, default=0)
    file_path = db.Column(db.String(500), nullable=False)
    pptist_json = db.Column(db.Text)  # PPTist 兼容 JSON（仅 PPTX，浏览器内解析后回存）
    source_type = db.Column(db.String(30), default='manual', index=True)  # manual/homework/activity
    source_id = db.Column(db.Integer, nullable=True, index=True)
    note = db.Column(db.String(500))
    created_at = db.Column(db.DateTime, default=datetime.now, index=True)

    student = db.relationship('Student', foreign_keys=[student_id],
                              backref=db.backref('drive_files', lazy=True, cascade='all, delete-orphan'))


class GroupJoinRequest(db.Model):
    """小组加入/退出申请"""
    __tablename__ = 'group_join_request'

    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('student.id'), nullable=False, index=True)
    group_id = db.Column(db.Integer, db.ForeignKey('study_group.id'), nullable=False, index=True)
    request_type = db.Column(db.String(10), nullable=False)  # 'join' or 'leave'
    status = db.Column(db.String(10), default='pending')  # pending/approved/rejected
    request_time = db.Column(db.DateTime, default=datetime.now)

    student = db.relationship('Student', foreign_keys=[student_id])
    group = db.relationship('StudyGroup', foreign_keys=[group_id])


class Schedule(db.Model):
    """作息时间表"""
    __tablename__ = 'schedule'

    id = db.Column(db.Integer, primary_key=True)
    period_name = db.Column(db.String(50), nullable=False)
    start_time = db.Column(db.String(10), nullable=False)
    end_time = db.Column(db.String(10), nullable=False)
    sort_order = db.Column(db.Integer, default=0)
    is_active = db.Column(db.Boolean, default=True)


class ClassSchedule(db.Model):
    """课程表 — 星期N第N节课对应哪个班级上课（支持同节次多个班）"""
    __tablename__ = 'class_schedule'
    __table_args__ = (
        db.UniqueConstraint('weekday', 'period_number', 'class_name',
                            name='uq_cs_weekday_period_class'),
    )

    id = db.Column(db.Integer, primary_key=True)
    weekday = db.Column(db.Integer, nullable=False, default=1, index=True)
    period_number = db.Column(db.Integer, nullable=False, index=True)
    class_name = db.Column(db.String(50), nullable=False)

    WEEKDAY_NAMES = {1: '星期一', 2: '星期二', 3: '星期三', 4: '星期四', 5: '星期五', 6: '星期六', 7: '星期日'}

    def __repr__(self):
        return f'<ClassSchedule {self.WEEKDAY_NAMES.get(self.weekday, "?")} #{self.period_number} -> {self.class_name}>'


class ClassroomSetting(db.Model):
    """课堂设置 — 兼容旧单班模型的全局默认设置"""
    __tablename__ = 'classroom_setting'

    id = db.Column(db.Integer, primary_key=True)
    active_class_id = db.Column(db.Integer, db.ForeignKey('classes.id'), nullable=True)
    current_schedule_id = db.Column(db.Integer, db.ForeignKey('schedule.id'), nullable=True)
    display_message = db.Column(db.String(500))
    seat_offset = db.Column(db.Integer, default=0)
    auto_switch = db.Column(db.Boolean, default=False)
    updated_at = db.Column(db.DateTime, default=datetime.now)

    active_class = db.relationship('Class', foreign_keys=[active_class_id])
    current_schedule = db.relationship('Schedule', foreign_keys=[current_schedule_id])


class ClassroomSession(db.Model):
    """按班级独立的课堂会话（多班大屏；同班唯一）"""
    __tablename__ = 'classroom_session'

    id = db.Column(db.Integer, primary_key=True)
    class_id = db.Column(db.Integer, db.ForeignKey('classes.id'),
                         nullable=False, unique=True, index=True)
    schedule_id = db.Column(db.Integer, db.ForeignKey('schedule.id'), nullable=True)
    display_message = db.Column(db.String(500), default='')
    seat_offset = db.Column(db.Integer, default=0)
    auto_switch = db.Column(db.Boolean, default=False)
    is_active = db.Column(db.Boolean, default=True, index=True)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

    class_ = db.relationship('Class', foreign_keys=[class_id])
    schedule = db.relationship('Schedule', foreign_keys=[schedule_id])

    @property
    def active_class(self):
        return self.class_

    @property
    def current_schedule(self):
        return self.schedule


class Student(db.Model):
    """学生表"""
    # 学号唯一约束：此前仅由运行时 migrate_db() 原始 SQL 创建，不在模型/
    # 迁移中导致 alembic autogenerate 与模型元数据漂移；纳入模型后新库
    # 建表自带约束，存量库由 migrate_db 兜底（幂等）
    __table_args__ = (
        db.UniqueConstraint('student_number', name='uq_student_number'),
    )
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), index=True)
    student_number = db.Column(db.String(50), index=True)
    student_class = db.Column(db.String(50), index=True)
    grade = db.Column(db.String(20))
    password_hash = db.Column(db.String(256))
    is_activated = db.Column(db.Boolean, default=True, index=True)
    has_changed_password = db.Column(db.Boolean, default=False)
    class_id = db.Column(db.Integer, db.ForeignKey('classes.id'), nullable=True, index=True)
    group_id = db.Column(db.Integer, db.ForeignKey('study_group.id'), nullable=True, index=True)
    ip_address = db.Column(db.String(50))
    login_time = db.Column(db.DateTime, nullable=True, index=True)
    last_seen = db.Column(db.DateTime, nullable=True, index=True)

    def set_password(self, password):
        """设置密码（使用 werkzeug pbkdf2:sha256）"""
        self.password_hash = generate_password_hash(password, method='pbkdf2:sha256')

    def check_password(self, password):
        """校验密码，兼容旧 sha256 格式（salt:hash）和新 pbkdf2 格式"""
        if not self.password_hash:
            return False
        # 旧格式：salt:sha256_hex（64 位小写十六进制）。
        # 显式匹配十六进制长度，避免把 scrypt:... 等其他 werkzeug 格式误判为旧格式
        # 而错误地拆成 salt='scrypt' 导致永远校验失败。
        if (':' in self.password_hash
                and not self.password_hash.startswith(('pbkdf2:', 'scrypt:'))):
            parts = self.password_hash.split(':', 1)
            if len(parts) == 2:
                salt, h = parts
                if re.fullmatch(r'[0-9a-f]{64}', h):
                    # 恒定时间比较，避免时序侧信道
                    ok = secrets.compare_digest(
                        h,
                        hashlib.sha256((salt + password).encode()).hexdigest()
                    )
                    if ok:
                        # 旧格式验证通过后自动升级为 pbkdf2:sha256（内存中更新，
                        # 由登录/改密流程的 commit 持久化；未保存时下次登录再次升级，无害）
                        self.set_password(password)
                    return ok
        # 新格式：pbkdf2:sha256:...
        return check_password_hash(self.password_hash, password)


class AdminAccount(db.Model):
    """管理员账号表（V5.0 多账号支持）"""
    __tablename__ = 'admin_account'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    display_name = db.Column(db.String(80))
    password_hash = db.Column(db.String(256), nullable=False)
    is_active = db.Column(db.Boolean, default=True, index=True)
    created_at = db.Column(db.DateTime, default=datetime.now)
    last_login_at = db.Column(db.DateTime, nullable=True)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

    def set_password(self, password):
        """设置密码（与 Teacher/Student 一致，pbkdf2:sha256）"""
        self.password_hash = generate_password_hash(password, method='pbkdf2:sha256')

    def check_password(self, password):
        try:
            return check_password_hash(self.password_hash, password)
        except (ValueError, TypeError):
            return False


class Teacher(db.Model):
    """教师账号表"""
    __tablename__ = 'teacher'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    display_name = db.Column(db.String(80))
    password_hash = db.Column(db.String(256), nullable=False)
    is_active = db.Column(db.Boolean, default=True, index=True)
    created_at = db.Column(db.DateTime, default=datetime.now)
    last_login_at = db.Column(db.DateTime, nullable=True)
    # 多学科归属；关联表定义在 Subject 之后
    subjects = db.relationship(
        'Subject', secondary='teacher_subject',
        backref=db.backref('teachers', lazy='dynamic'), lazy='selectin')
    grade = db.Column(db.String(50), nullable=True, index=True)
    classes = db.relationship(
        'Class', secondary='teacher_class',
        backref=db.backref('teachers', lazy='dynamic'), lazy='selectin')

    def set_password(self, password):
        self.password_hash = generate_password_hash(password, method='pbkdf2:sha256')

    def check_password(self, password):
        if not self.password_hash:
            return False
        return check_password_hash(self.password_hash, password)


class ExamQuestion(db.Model):
    """试卷-试题关联（多对多 + 卷内排序）

    架构：试题与试卷解耦——同一题可归属 0~N 套试卷（exam_question），
    Question.exam_id 仅作"创建来源卷"溯源（可空，不再用于归属查询）。
    组卷/移除/排序操作本表；建题带 exam_id 时由事件自动挂卷（兼容旧流程）。
    """
    __tablename__ = 'exam_question'
    __table_args__ = (
        db.UniqueConstraint('exam_id', 'question_id', name='uq_exam_question'),
    )

    id = db.Column(db.Integer, primary_key=True)
    exam_id = db.Column(db.Integer, db.ForeignKey('exam.id'),
                        nullable=False, index=True)
    question_id = db.Column(db.Integer, db.ForeignKey('question.id'),
                            nullable=False, index=True)
    position = db.Column(db.Integer, nullable=False, default=0)

    # 删题时级联清理各卷关联行（题目入题库不受卷删除影响）
    question = db.relationship(
        'Question',
        backref=db.backref('exam_links', cascade='all, delete-orphan',
                           lazy=True))


class Exam(db.Model):
    """试卷表"""
    # 试卷名全局唯一（应用层四处查重 + 批量导入按卷名避让均依赖此约定；
    # 数据库约束兜底并发下的 check-then-insert 竞态）
    __table_args__ = (
        db.UniqueConstraint('name', name='uq_exam_name'),
    )
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), index=True)
    subject_id = db.Column(db.Integer, db.ForeignKey('subject.id'), nullable=True, index=True)
    create_time = db.Column(db.DateTime, default=datetime.now, index=True)
    is_active = db.Column(db.Boolean, default=True, index=True)
    is_visible = db.Column(db.Boolean, default=True, index=True)
    is_enabled = db.Column(db.Boolean, default=True, index=True)
    is_collected = db.Column(db.Boolean, default=False, index=True)
    allow_view_results = db.Column(db.Boolean, default=True)
    duration = db.Column(db.Integer, nullable=True)  # 考试时长（分钟），NULL/0表示不限时

    # 组卷关联（viewonly：增删/排序一律显式操作 ExamQuestion，避免双写歧义）。
    # order_by position —— 卷内题目序（组卷接口维护）
    questions = db.relationship(
        'Question', secondary='exam_question',
        order_by='ExamQuestion.position', lazy=True,
        backref=db.backref('exams', lazy=True),
        viewonly=True)


class SubQuestion(db.Model):
    """综合题小题模型"""
    id = db.Column(db.Integer, primary_key=True)
    question_id = db.Column(db.Integer, db.ForeignKey('question.id'), nullable=False)
    question_type = db.Column(db.String(20), nullable=False)
    content = db.Column(db.Text, nullable=False)
    options = db.Column(db.Text)
    image_options = db.Column(db.Text)
    answer = db.Column(db.Text, nullable=True)
    score = db.Column(db.Float, nullable=False)
    order = db.Column(db.Integer, nullable=False)
    blank_scores = db.Column(db.Text)
    image_url = db.Column(db.Text)

    @property
    def blank_scores_list(self):
        if not self.blank_scores:
            return []
        try:
            return json.loads(self.blank_scores)
        except Exception:
            return []

    @property
    def sorted_options(self):
        return normalize_options(self.options)

    @property
    def image_options_dict(self):
        if not self.image_options:
            return {}
        try:
            return json.loads(self.image_options)
        except Exception:
            return {}


class Question(db.Model):
    """试题模型

    归属架构（解耦）：本表不再表达"属于哪套试卷"——归属关系在
    ExamQuestion 中间表（同一题 0~N 卷）。exam_id 仅为创建来源卷
    （可空，溯源/旧流程兼容；建题带值时由事件自动挂卷）。
    """
    id = db.Column(db.Integer, primary_key=True)
    exam_id = db.Column(db.Integer, db.ForeignKey('exam.id'), nullable=True)
    # 题型索引：api_exams 的「外链卷」判定按 question_type 过滤且无 exam_id
    # 锚点（学生视图无缓存，每次打开试卷列表都跑一次全表 join 后过滤）
    question_type = db.Column(db.String(20), nullable=False, index=True)
    content = db.Column(db.Text, nullable=False)
    options = db.Column(db.Text)
    image_options = db.Column(db.Text)
    answer = db.Column(db.Text, nullable=True)
    score = db.Column(db.Float, nullable=False)
    python_answers = db.Column(db.Text)
    blank_scores = db.Column(db.Text)  # JSON 数组：python_fill 每空分值（如 [3,3,4]）
    background = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.now)
    image_url = db.Column(db.Text)
    footer_content = db.Column(db.Text)

    # 来源卷关系（溯源用；不再 backref questions——卷内题目关系见 Exam.questions）
    exam = db.relationship('Exam')
    sub_questions = db.relationship('SubQuestion', backref='question', lazy=True,
                                    cascade='all, delete-orphan')

    @property
    def sorted_options(self):
        return normalize_options(self.options)

    @property
    def image_options_dict(self):
        if not self.image_options:
            return {}
        try:
            return json.loads(self.image_options)
        except Exception:
            return {}

    @property
    def python_answers_dict(self):
        if not self.python_answers:
            return {}
        try:
            return json.loads(self.python_answers)
        except Exception:
            return {}

    @property
    def blank_scores_list(self):
        """python_fill 每空分值列表（与 SubQuestion 同名属性对齐）；
        缺失/非列表时返回空列表，由判分方兜底均分。"""
        if not self.blank_scores:
            return []
        try:
            data = json.loads(self.blank_scores)
            return data if isinstance(data, list) else []
        except Exception:
            return []

    @property
    def python_blanks_dict(self):
        if self.question_type != 'python_fill':
            return {}
        blanks = {}
        content = self.content
        pattern = r'<span class="python-blank" id="blank_([^"]+)">([^<]+)</span>'
        matches = re.findall(pattern, content)
        for blank_id, placeholder in matches:
            blanks[blank_id] = placeholder
        if not blanks and self.python_answers:
            for blank_id in self.python_answers_dict.keys():
                blanks[blank_id] = "____"
        return blanks


# ── 题库/试卷解耦：统一排序与组卷助手 ─────────────────────
# 卷内题目顺序 = 题型固定分组（单选→多选→判断→填空→简答→Python→综合→外链）
# + 组内 position（组卷接口维护）。全局题号 1..N 由 exam_questions_ordered 生成，
# 考试页/成绩页/批改/统计/导出共用，保证全站口径一致。
QUESTION_TYPE_ORDER = {'single': 0, 'multiple': 1, 'judge': 2, 'fill': 3,
                       'short_answer': 4, 'python_fill': 5,
                       'comprehensive': 6, 'link': 9}

# 题型分组展示标签（考试页分组标题条；键与 QUESTION_TYPE_ORDER 对齐）
QUESTION_TYPE_LABELS = {
    'single': '一、单选题', 'multiple': '二、多选题', 'judge': '三、判断题',
    'fill': '四、填空题', 'short_answer': '五、简答题',
    'python_fill': '六、Python填空题', 'comprehensive': '七、综合题',
    'link': '外链试卷',
}


def next_exam_position(exam_id):
    """卷内追加位次（max+1）"""
    from sqlalchemy import func
    row = db.session.query(func.max(ExamQuestion.position)) \
        .filter(ExamQuestion.exam_id == exam_id).first()
    return (row[0] or 0) + 1


def link_question_to_exam(question_id, exam_id, position=None):
    """把题目挂到试卷（幂等；默认追加到卷尾）"""
    exists = ExamQuestion.query.filter_by(
        exam_id=exam_id, question_id=question_id).first()
    if exists:
        return exists
    link = ExamQuestion(exam_id=exam_id, question_id=question_id,
                        position=position or next_exam_position(exam_id))
    db.session.add(link)
    return link


def unlink_question_from_exam(question_id, exam_id):
    """把题目移出试卷（返回是否删除了行）"""
    n = ExamQuestion.query.filter_by(
        exam_id=exam_id, question_id=question_id).delete(
        synchronize_session=False)
    return n > 0


def link_questions_to_exam_bulk(question_ids, exam_id):
    """批量挂题（幂等）：一次摸清已入卷集合 + 一次性分配位次。

    逐题调用 link_question_to_exam 时每题 1 次存在性 SELECT + 1 次
    MAX(position) SELECT，且自动 flush 使每次 insert 单独往返——给试卷加入
    200 题题库约 400 次 SELECT + 200 次 flush。此处合并为 2 次查询与 1 次
    批量 insert（调用方随后 resequence_exam 重排，位次仅需唯一）。
    返回实际新增题数。
    """
    from sqlalchemy import func
    qids = list(dict.fromkeys(int(q) for q in question_ids))
    if not qids:
        return 0
    existing = {
        qid for (qid,) in db.session.query(ExamQuestion.question_id).filter(
            ExamQuestion.exam_id == exam_id,
            ExamQuestion.question_id.in_(qids)).all()
    }
    row = db.session.query(func.max(ExamQuestion.position)) \
        .filter(ExamQuestion.exam_id == exam_id).first()
    base = (row[0] or 0) + 1
    added = 0
    for qid in qids:
        if qid in existing:
            continue
        existing.add(qid)
        db.session.add(ExamQuestion(exam_id=exam_id, question_id=qid,
                                    position=base + added))
        added += 1
    return added


def resequence_exam(exam_id):
    """按当前排序规则重排卷内 position（1..N，删除/插入后保持紧凑）"""
    from sqlalchemy.orm import joinedload
    rows = (db.session.query(ExamQuestion)
            .options(joinedload(ExamQuestion.question))
            .join(Question, Question.id == ExamQuestion.question_id)
            .filter(ExamQuestion.exam_id == exam_id).all())
    ordered = sorted(rows, key=lambda lk: (
        QUESTION_TYPE_ORDER.get(lk.question.question_type, 8),
        lk.position, lk.question_id))
    for i, link in enumerate(ordered, 1):
        link.position = i
    return len(ordered)


def exam_questions_ordered(exam_id):
    """卷内题目（题型分组序）：返回 [(question, 全局题号)]"""
    rows = (db.session.query(Question, ExamQuestion.position)
            .join(ExamQuestion, ExamQuestion.question_id == Question.id)
            .filter(ExamQuestion.exam_id == exam_id).all())
    rows.sort(key=lambda qp: (
        QUESTION_TYPE_ORDER.get(qp[0].question_type, 8), qp[1], qp[0].id))
    return [(q, i + 1) for i, (q, _p) in enumerate(rows)]


def exam_questions_flat(exam_id):
    """卷内题目有序列表（仅 Question）"""
    return [q for q, _seq in exam_questions_ordered(exam_id)]


def exam_total_score(exam_id):
    """试卷总分 = 卷内各题分值汇总"""
    return round(sum(q.score or 0 for q in exam_questions_flat(exam_id)), 2)


from sqlalchemy import event as _sa_event  # noqa: E402  — 需在模型类定义后注册


@_sa_event.listens_for(Question, 'after_insert')
def _question_auto_link_exam(mapper, connection, target):
    """建题带 exam_id（创建来源卷）时自动挂卷到卷尾——兼容旧流程与
    既有调用方/测试；纯题库题（exam_id=NULL）不产生关联。"""
    if target.exam_id:
        connection.execute(
            text('INSERT INTO exam_question (exam_id, question_id, position) '
                 'VALUES (:e, :q, COALESCE((SELECT MAX(position) '
                 'FROM exam_question WHERE exam_id = :e), 0) + 1)'),
            {'e': target.exam_id, 'q': target.id})


class Result(db.Model):
    """成绩表"""
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('student.id'), index=True)
    exam_id = db.Column(db.Integer, db.ForeignKey('exam.id'), index=True)
    answers = db.Column(db.Text)
    scores = db.Column(db.Text)
    total_score = db.Column(db.Float, index=True)
    submit_time = db.Column(db.DateTime, default=datetime.now, index=True)
    grading_status = db.Column(db.String(20), default='auto_graded', index=True)
    manual_scores = db.Column(db.Text, nullable=True)  # JSON: {"Q_id": {"max_score": 10, "manual_score": null, "student_answer": "..."}}
    graded_by = db.Column(db.Integer, nullable=True)
    graded_at = db.Column(db.DateTime, nullable=True)

    __table_args__ = (
        db.Index('ix_result_student_exam', 'student_id', 'exam_id'),
        db.Index('ix_result_exam_submit', 'exam_id', 'submit_time'),
        db.UniqueConstraint('student_id', 'exam_id', name='uq_result_student_exam'),
    )


class ExamAttempt(db.Model):
    """考试进行中记录 — 服务端记录开考时间，供提交时长强校验使用。

    持久化到 DB 而非易失缓存：缓存被驱逐时时长校验会静默跳过（fail-open），
    学生可在超时后无限时提交。提交成功/超时拒绝后记录被清理。
    """
    __tablename__ = 'exam_attempt'

    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('student.id'), nullable=False, index=True)
    exam_id = db.Column(db.Integer, db.ForeignKey('exam.id'), nullable=False, index=True)
    start_time = db.Column(db.DateTime, default=datetime.now, nullable=False)

    __table_args__ = (
        db.UniqueConstraint('student_id', 'exam_id', name='uq_exam_attempt_student_exam'),
    )


class Subject(db.Model):
    """学科表"""
    __tablename__ = 'subject'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)
    sort_order = db.Column(db.Integer, default=0)

    resources = db.relationship('Resource', backref='subject', lazy=True)
    exams = db.relationship('Exam', backref='subject', lazy=True)


# 教师-学科多对多（教师可归属多个学科）
teacher_subject = db.Table(
    'teacher_subject',
    db.Column('teacher_id', db.Integer, db.ForeignKey('teacher.id'),
              primary_key=True),
    db.Column('subject_id', db.Integer, db.ForeignKey('subject.id'),
              primary_key=True, index=True),
)

# 教师任课班级（教师可带多个班级；年级存放在 teacher.grade）
teacher_class = db.Table(
    'teacher_class',
    db.Column('teacher_id', db.Integer, db.ForeignKey('teacher.id'),
              primary_key=True),
    db.Column('class_id', db.Integer, db.ForeignKey('classes.id'),
              primary_key=True, index=True),
)


class Appeal(db.Model):
    """学生申诉表"""
    __tablename__ = 'appeal'

    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('student.id'), nullable=False, index=True)
    message = db.Column(db.String(200), nullable=False)
    create_time = db.Column(db.DateTime, default=datetime.now)
    is_read = db.Column(db.Boolean, default=False)

    student = db.relationship('Student', foreign_keys=[student_id])


class Resource(db.Model):
    """学习资源表"""
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200))
    url = db.Column(db.String(500))
    subject_id = db.Column(db.Integer, db.ForeignKey('subject.id'), nullable=True)
    homework_files = db.Column(db.Text)  # JSON: ["file1.html", "subfolder/file2.pdf"]
    file_permissions = db.Column(db.Text)  # JSON: {"file1.html": {"show": true, "download": true}}
    # 允许学生打开主页/已展示页面链接到的同资源隐藏文件（文件列表仍只显示
    # “展示”文件）；用于自包含课件包的子页面与 CSS/JS/图片等依赖。
    allow_related_files = db.Column(db.Boolean, default=False)
    show_in_student = db.Column(db.Boolean, default=True)  # 学生端可见
    show_in_classroom = db.Column(db.Boolean, default=True)  # 课堂教学端可见
    quiz_mode = db.Column(db.String(20), default='inject')  # inject/runtime/none
    injected = db.Column(db.Boolean, default=False)  # 是否已磁盘注入 SD
    backup_path = db.Column(db.String(500))  # 注入前备份路径
    quiz_pending_files = db.Column(db.Text)  # JSON: 待检测/待注入的 HTML 相对路径
    quiz_inject_state = db.Column(db.String(20), default='none')  # none/pending/partial/verified
    lesson_tree = db.Column(db.Text)  # JSON: 课堂章节树 [{id,title,type:section,children,items:[{id,title,kind,src,doc_category,visible,activity_id}]}]
    # 创建者与教师只读共享
    creator_teacher_id = db.Column(
        db.Integer, db.ForeignKey('teacher.id'), nullable=True, index=True)
    creator_type = db.Column(db.String(20), default='admin')  # admin/teacher
    creator_name = db.Column(db.String(80), nullable=True)
    # 公开资源：全体教师在课堂模式可见可用（仅管理员可编辑）
    is_public = db.Column(db.Boolean, default=False)
    # 内置资源（随版本分发的系统资源，如铜匠实验室）：管理员可改元数据并
    # 停用（墓碑），课件内容随版本升级；builtin_key 用于种子幂等与恢复
    is_builtin = db.Column(db.Boolean, default=False, index=True)
    builtin_key = db.Column(db.String(64), nullable=True, index=True)
    creator_teacher = db.relationship(
        'Teacher', foreign_keys=[creator_teacher_id])
    shared_teachers = db.relationship(
        'Teacher', secondary='resource_share', lazy='selectin',
        backref=db.backref('shared_resources', lazy='dynamic'))


# 资源-教师只读共享（按教师多选授权；所有记录均为只读）
resource_share = db.Table(
    'resource_share',
    db.Column('resource_id', db.Integer, db.ForeignKey('resource.id'),
              primary_key=True),
    db.Column('teacher_id', db.Integer, db.ForeignKey('teacher.id'),
              primary_key=True, index=True),
    db.Column('created_at', db.DateTime, default=datetime.now),
)


# 内置资源的年级×学科授权范围（交集+通配语义）：
# 每条记录表示「年级 grade（NULL=不限年级）且学科 subject_id（NULL=不限学科）
# 的教师可用该资源」；命中任一记录即视为已授权。资源存在授权记录时，
# 以授权记录为准（覆盖 is_public 旧语义）；无记录时回退 is_public。
resource_audience = db.Table(
    'resource_audience',
    db.Column('id', db.Integer, primary_key=True),
    db.Column('resource_id', db.Integer,
              db.ForeignKey('resource.id', ondelete='CASCADE'),
              nullable=False, index=True),
    db.Column('grade', db.String(50), nullable=True),
    db.Column('subject_id', db.Integer, db.ForeignKey('subject.id'),
              nullable=True, index=True),
    db.Column('created_at', db.DateTime, default=datetime.now),
    db.UniqueConstraint('resource_id', 'grade', 'subject_id',
                        name='uq_resource_audience_scope'),
)


class LearningActivity(db.Model):
    """挂载在学习资源下的学习活动"""
    __tablename__ = 'learning_activity'

    id = db.Column(db.Integer, primary_key=True)
    # 复合索引覆盖 resources.py:38 按 (resource_id, is_active) 的过滤，
    # 单列索引无法同时命中两列
    __table_args__ = (
        db.Index('ix_learning_activity_resource_active',
                 'resource_id', 'is_active'),
    )
    resource_id = db.Column(db.Integer, db.ForeignKey('resource.id'), nullable=False, index=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    document_path = db.Column(db.String(500))
    document_name = db.Column(db.String(255))
    require_upload = db.Column(db.Boolean, default=False, index=True)
    upload_type = db.Column(db.String(20), default='file')
    sort_order = db.Column(db.Integer, default=0)
    is_active = db.Column(db.Boolean, default=True, index=True)
    start_time = db.Column(db.DateTime, nullable=True)  # 提交时间窗（可空=不限开始）
    end_time = db.Column(db.DateTime, nullable=True)    # 提交时间窗（可空=不限结束）
    capacity = db.Column(db.Integer, nullable=True)     # 报名/提交人数上限（可空=不限）
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

    resource = db.relationship('Resource', foreign_keys=[resource_id],
                               backref=db.backref('activities', lazy=True, cascade='all, delete-orphan'))


class StudentWork(db.Model):
    """学生学习活动作品"""
    __tablename__ = 'student_work'
    __table_args__ = (
        db.UniqueConstraint('activity_id', 'student_id', name='uq_student_work_activity_student'),
    )

    id = db.Column(db.Integer, primary_key=True)
    activity_id = db.Column(db.Integer, db.ForeignKey('learning_activity.id'), nullable=False, index=True)
    student_id = db.Column(db.Integer, db.ForeignKey('student.id'), nullable=False, index=True)
    title = db.Column(db.String(200))
    work_type = db.Column(db.String(20), default='file')
    original_filename = db.Column(db.String(255))
    file_path = db.Column(db.String(500))
    file_size = db.Column(db.Integer, default=0)
    text_content = db.Column(db.Text)
    status = db.Column(db.String(20), default='submitted', index=True)
    submitted_at = db.Column(db.DateTime, default=datetime.now, index=True)
    public_token = db.Column(db.String(64), unique=True, index=True,
                             default=lambda: uuid.uuid4().hex)
    is_excellent = db.Column(db.Boolean, default=False, index=True)

    activity = db.relationship('LearningActivity', foreign_keys=[activity_id],
                               backref=db.backref('works', lazy=True, cascade='all, delete-orphan'))
    student = db.relationship('Student', foreign_keys=[student_id])


class WorkEvaluation(db.Model):
    """学生作品评价"""
    __tablename__ = 'work_evaluation'

    id = db.Column(db.Integer, primary_key=True)
    work_id = db.Column(db.Integer, db.ForeignKey('student_work.id'), nullable=False, unique=True, index=True)
    score = db.Column(db.Float, nullable=True)
    grade = db.Column(db.String(20))
    comment = db.Column(db.Text)
    evaluated_by = db.Column(db.String(80))
    evaluated_at = db.Column(db.DateTime, default=datetime.now, index=True)

    work = db.relationship('StudentWork', foreign_keys=[work_id],
                           backref=db.backref('evaluation', uselist=False, cascade='all, delete-orphan'))


class ExcellenceThreshold(db.Model):
    """优秀作品自动标记阈值"""
    __tablename__ = 'excellence_threshold'

    id = db.Column(db.Integer, primary_key=True)
    activity_id = db.Column(db.Integer, db.ForeignKey('learning_activity.id'), nullable=False, unique=True, index=True)
    min_score = db.Column(db.Float, default=90)
    grade_levels = db.Column(db.String(200), default='A+,A')
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

    activity = db.relationship('LearningActivity', foreign_keys=[activity_id],
                               backref=db.backref('excellence_threshold', uselist=False, cascade='all, delete-orphan'))


class Survey(db.Model):
    """调查问卷（挂载在学习资源下；题型与统计口径借鉴 SurveyKing，MIT）"""
    __tablename__ = 'survey'

    id = db.Column(db.Integer, primary_key=True)
    resource_id = db.Column(db.Integer, db.ForeignKey('resource.id'),
                            nullable=False, index=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    status = db.Column(db.String(20), default='draft', index=True)  # draft/published/closed
    is_anonymous = db.Column(db.Boolean, default=False)  # 结果不显示答题人
    start_time = db.Column(db.DateTime, nullable=True)  # 填写时间窗（可空=不限）
    end_time = db.Column(db.DateTime, nullable=True)
    sort_order = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

    resource = db.relationship('Resource', foreign_keys=[resource_id],
                               backref=db.backref('surveys', lazy=True,
                                                  cascade='all, delete-orphan'))
    questions = db.relationship('SurveyQuestion',
                                backref='survey', lazy=True,
                                cascade='all, delete-orphan',
                                order_by='SurveyQuestion.sort_order')


class SurveyQuestion(db.Model):
    """问卷题目（选项与矩阵行为 JSON 文本）"""
    __tablename__ = 'survey_question'

    id = db.Column(db.Integer, primary_key=True)
    survey_id = db.Column(db.Integer, db.ForeignKey('survey.id'),
                          nullable=False, index=True)
    # radio/checkbox/select/text/textarea/score/matrix_radio/matrix_score
    q_type = db.Column(db.String(20), nullable=False)
    title = db.Column(db.String(500), nullable=False)
    options = db.Column(db.Text)      # JSON: ["选项1", ...]
    row_titles = db.Column(db.Text)   # JSON: ["矩阵行1", ...]（矩阵题）
    required = db.Column(db.Boolean, default=False)
    sort_order = db.Column(db.Integer, default=0)


class SurveyAnswer(db.Model):
    """问卷答卷（每学生每问卷一份）"""
    __tablename__ = 'survey_answer'
    __table_args__ = (
        db.UniqueConstraint('survey_id', 'student_id',
                            name='uq_survey_answer_survey_student'),
    )

    id = db.Column(db.Integer, primary_key=True)
    survey_id = db.Column(db.Integer, db.ForeignKey('survey.id'),
                          nullable=False, index=True)
    student_id = db.Column(db.Integer, db.ForeignKey('student.id'),
                           nullable=False, index=True)
    # JSON: {"<question_id>": 值}；选择题存选项文本，矩阵存 {"<row>": 选项/分值}
    answers = db.Column(db.Text)
    submitted_at = db.Column(db.DateTime, default=datetime.now, index=True)

    survey = db.relationship('Survey', foreign_keys=[survey_id])
    student = db.relationship('Student', foreign_keys=[student_id])


class TeachingSession(db.Model):
    """教师上课/下课教学记录"""
    __tablename__ = 'teaching_session'

    id = db.Column(db.Integer, primary_key=True)
    resource_id = db.Column(db.Integer, db.ForeignKey('resource.id'), nullable=False, index=True)
    teacher_id = db.Column(db.Integer, db.ForeignKey('teacher.id'), nullable=True, index=True)
    teacher_name = db.Column(db.String(80), nullable=False, index=True)
    start_time = db.Column(db.DateTime, default=datetime.now, index=True)
    end_time = db.Column(db.DateTime, nullable=True, index=True)
    duration_minutes = db.Column(db.Integer, nullable=True)
    attendance_snapshot = db.Column(db.Text)
    status = db.Column(db.String(20), default='active', index=True)
    class_id = db.Column(db.Integer, db.ForeignKey('classes.id'),
                         nullable=True, index=True)

    resource = db.relationship('Resource', foreign_keys=[resource_id])
    teacher = db.relationship('Teacher', foreign_keys=[teacher_id])


class SystemConfig(db.Model):
    """系统开关配置表"""
    __tablename__ = 'system_config'

    key = db.Column(db.String(100), primary_key=True)
    value = db.Column(db.String(500), nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

    # 全表缓存（TTL 5s）：_enforce_system_switches 在每个请求上调用
    # get_bool 两次，250 并发下逐请求查库是纯开销；开关变更频率极低，
    # 5 秒延迟可接受，且 set() 会主动失效。
    # 走 Flask-Caching（filesystem）：多进程部署时配置变更可跨进程一致
    # 生效（原进程内类变量缓存仅单进程内有效）。仅在应用上下文中调用。

    @staticmethod
    def _load_all():
        from app.extensions import cache
        data = cache.get('system_config:all')
        if data is None:
            rows = SystemConfig.query.all()
            data = {row.key: row.value for row in rows}
            cache.set('system_config:all', data, timeout=5)
        return data

    @staticmethod
    def _invalidate_cache():
        from app.extensions import cache
        cache.delete('system_config:all')

    @staticmethod
    def get(key, default=None):
        return SystemConfig._load_all().get(key, default)

    @staticmethod
    def get_bool(key, default=True):
        value = SystemConfig.get(key, 'true' if default else 'false')
        return str(value).lower() in ('1', 'true', 'yes', 'on')

    @staticmethod
    def set(key, value):
        row = SystemConfig.query.filter_by(key=key).first()
        value = str(value)
        if row:
            row.value = value
            row.updated_at = datetime.now()
        else:
            db.session.add(SystemConfig(key=key, value=value))
        SystemConfig._invalidate_cache()


# 作业-班级多对多关联表
homework_classes = db.Table('homework_classes',
    db.Column('homework_id', db.Integer, db.ForeignKey('homework.id'), primary_key=True),
    # class_id 需独立索引：复合主键是最左前缀 (homework_id, class_id)，
    # 而「本班活跃作业数」正是按 class_id 单列过滤（homework.py:1154）
    db.Column('class_id', db.Integer, db.ForeignKey('classes.id'), primary_key=True, index=True)
)


class Homework(db.Model):
    """作业表"""
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    subject_id = db.Column(db.Integer, db.ForeignKey('subject.id'), nullable=True)
    attachments = db.Column(db.Text)  # JSON: ["file1.pdf", "subdir/img.png"]
    deadline = db.Column(db.DateTime, nullable=True)
    create_time = db.Column(db.DateTime, default=datetime.now)
    # 历史设计错误曾把该列声明为 REFERENCES student(id)，导致教师 ID 无法写入
    # （教师不是学生），创建者信息丢失。现为普通整数列，语义为 Teacher.id。
    teacher_id = db.Column(db.Integer, nullable=True)
    is_active = db.Column(db.Boolean, default=True)

    subject = db.relationship('Subject', foreign_keys=[subject_id])
    teacher = db.relationship('Teacher', foreign_keys=[teacher_id],
                              primaryjoin='Homework.teacher_id == Teacher.id')
    classes = db.relationship('Class', secondary=homework_classes, lazy='dynamic',
                              backref=db.backref('homeworks', lazy='dynamic'))
    submissions = db.relationship('HomeworkSubmission', backref='homework', lazy=True,
                                   cascade='all, delete-orphan')


class HomeworkSubmission(db.Model):
    """作业提交表"""
    __tablename__ = 'homework_submission'

    id = db.Column(db.Integer, primary_key=True)
    homework_id = db.Column(db.Integer, db.ForeignKey('homework.id'), nullable=False, index=True)
    student_id = db.Column(db.Integer, db.ForeignKey('student.id'), nullable=False, index=True)
    text_content = db.Column(db.Text)
    files = db.Column(db.Text)  # JSON: uploaded file paths
    submit_time = db.Column(db.DateTime, default=datetime.now, index=True)
    resubmit_time = db.Column(db.DateTime, nullable=True)
    grade = db.Column(db.String(4), nullable=True, index=True)
    feedback = db.Column(db.Text)
    graded_at = db.Column(db.DateTime, nullable=True)
    # 普通整数列（语义为 Teacher.id），不再指向 student 表 —— 教师批改者 ID
    graded_by = db.Column(db.Integer, nullable=True)
    status = db.Column(db.String(20), default='submitted', index=True)  # submitted/graded

    student = db.relationship('Student', foreign_keys=[student_id])
    grader = db.relationship('Teacher', foreign_keys=[graded_by],
                             primaryjoin='HomeworkSubmission.graded_by == Teacher.id')

    __table_args__ = (
        # 防止双击/并发产生重复提交记录（此前仅靠查询检查，非原子）
        db.UniqueConstraint('homework_id', 'student_id',
                            name='uq_homework_submission_student'),
    )


class Log(db.Model):
    """操作日志表"""
    # 单条明细上限：防止拼接上下文超长导致表膨胀（tools/archive_logs.py 按月归档）
    DETAIL_MAX_LEN = 2000

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, index=True)
    user_type = db.Column(db.String(20), index=True)
    action = db.Column(db.String(100), index=True)
    detail = db.Column(db.Text)
    time = db.Column(db.DateTime, default=datetime.now, index=True)

    __table_args__ = (
        db.Index('ix_log_time_user', 'time', 'user_id'),
    )

    def __init__(self, **kwargs):
        if kwargs.get('detail') and len(kwargs['detail']) > Log.DETAIL_MAX_LEN:
            kwargs['detail'] = kwargs['detail'][:Log.DETAIL_MAX_LEN] + '…(截断)'
        super().__init__(**kwargs)


class AccountSession(db.Model):
    """一次登录对应一个终端会话（同账号多终端各自独立）。

    logout_at 仅在正常退出/会话被服务端清理时写入；浏览器直接关闭时保留
    last_seen_at，管理端按“最后活跃”展示，不伪造退出时间。
    """
    __tablename__ = 'account_session'

    id = db.Column(db.String(32), primary_key=True,
                   default=lambda: uuid.uuid4().hex)
    account_type = db.Column(db.String(16), nullable=False, index=True)
    account_id = db.Column(db.Integer, nullable=True, index=True)
    account_name = db.Column(db.String(80), nullable=True)
    channel = db.Column(db.String(16), default='web')  # web/api
    login_at = db.Column(db.DateTime, default=datetime.now, index=True)
    login_ip = db.Column(db.String(64))
    user_agent = db.Column(db.String(500))
    last_seen_at = db.Column(db.DateTime, default=datetime.now, index=True)
    logout_at = db.Column(db.DateTime, nullable=True, index=True)
    logout_reason = db.Column(db.String(32), nullable=True)
    page_count = db.Column(db.Integer, default=0)

    __table_args__ = (
        db.Index('ix_account_session_type_login',
                 'account_type', 'login_at'),
        db.Index('ix_account_session_account_login',
                 'account_id', 'login_at'),
    )


class AccountPageView(db.Model):
    """账号访问的 HTML 页面轨迹（不含查询串，避免记录令牌）。"""
    __tablename__ = 'account_page_view'

    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(
        db.String(32), db.ForeignKey('account_session.id', ondelete='CASCADE'),
        nullable=False, index=True)
    account_type = db.Column(db.String(16), index=True)
    account_id = db.Column(db.Integer, nullable=True, index=True)
    endpoint = db.Column(db.String(120), nullable=True)
    path = db.Column(db.String(500), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.now, index=True)

    __table_args__ = (
        db.Index('ix_account_page_session_time', 'session_id', 'created_at'),
    )


class PythonFile(db.Model):
    """Python试题文件表"""
    id = db.Column(db.Integer, primary_key=True)
    question_id = db.Column(db.Integer, db.ForeignKey('question.id'), nullable=False)
    file_name = db.Column(db.String(255), nullable=False)
    file_path = db.Column(db.String(500), nullable=False)  # 磁盘相对路径
    created_at = db.Column(db.DateTime, default=datetime.now)

    def get_absolute_path(self, upload_folder):
        """返回文件的绝对路径"""
        import os
        return os.path.join(upload_folder, self.file_path) if self.file_path else None

    def read_content(self, upload_folder):
        """读取文件内容（文本；UTF-8 → GBK → 容错，与学生答案同一解码口径）。

        此前只按 UTF-8 读：Windows 编辑器以 GBK 保存、含中文注释的参考文件
        解码失败，异常被判分入口吞掉 → 全体学生该题 0 分且无任何提示。
        """
        abs_path = self.get_absolute_path(upload_folder)
        if abs_path and os.path.exists(abs_path):
            from app.services.scoring_service import decode_python_source
            with open(abs_path, 'rb') as f:
                return decode_python_source(f.read())
        return None


class PythonAnswer(db.Model):
    """Python答案文件模型"""
    id = db.Column(db.Integer, primary_key=True)
    question_id = db.Column(db.Integer, db.ForeignKey('question.id'), nullable=False, index=True)
    student_id = db.Column(db.Integer, db.ForeignKey('student.id'), nullable=False, index=True)
    file_name = db.Column(db.String(255), nullable=False)
    file_path = db.Column(db.String(500), nullable=False)  # 磁盘相对路径
    score = db.Column(db.Float)
    status = db.Column(db.String(20), default='pending', index=True)
    feedback = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.now)
    graded_at = db.Column(db.DateTime)
    graded_by = db.Column(db.Integer)

    # 同学生同题唯一（防并发上传产生重复答案行，评分/批改各取一行口径不一致）
    __table_args__ = (
        db.UniqueConstraint('question_id', 'student_id',
                            name='uq_python_answer_student_question'),
    )

    def get_absolute_path(self, upload_folder):
        """返回文件的绝对路径"""
        import os
        return os.path.join(upload_folder, self.file_path) if self.file_path else None

    def read_content(self, upload_folder):
        """读取文件内容（文本；UTF-8 → GBK → 容错）"""
        abs_path = self.get_absolute_path(upload_folder)
        if abs_path and os.path.exists(abs_path):
            from app.services.scoring_service import decode_python_source
            with open(abs_path, 'rb') as f:
                return decode_python_source(f.read())
        return None


class ResourceQuizResult(db.Model):
    """资源内嵌测验成绩表"""
    __tablename__ = 'resource_quiz_result'
    # 同一学生、同一资源、同一测验文件唯一；quiz_key='legacy' 保留旧版
    # 单文件资源的历史成绩，同一资源内多个 HTML 测验不再互相覆盖。
    __table_args__ = (
        db.UniqueConstraint('student_id', 'resource_id', 'quiz_key',
                            name='uq_resource_quiz_student_file'),
    )

    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('student.id'), nullable=False)
    resource_id = db.Column(db.Integer, db.ForeignKey('resource.id'), nullable=False)
    source_file = db.Column(db.String(500))  # 资源内 HTML 相对路径
    quiz_key = db.Column(db.String(120), nullable=False, default='legacy')
    adapter_version = db.Column(db.Integer)
    question_details = db.Column(db.Text)  # JSON: 逐题题干、选项、作答及判定依据
    quiz_name = db.Column(db.String(200))
    answers = db.Column(db.Text)
    scores = db.Column(db.Text)
    total_score = db.Column(db.Float)
    max_score = db.Column(db.Float)
    # 客户端自报结果的扩展形态（v5.0.0 新增）：纯等级测验/证书测验
    # （无分数）或"答对题数/总题数"式测验，用以下字段记录；
    # 等级归一化为中文（优秀/良好/合格/不合格），未提供时由
    # total/max 百分比推导（≥90/≥80/≥60）
    grade = db.Column(db.String(20))
    correct_count = db.Column(db.Integer)
    question_count = db.Column(db.Integer)
    duration = db.Column(db.Integer)
    submit_time = db.Column(db.DateTime, default=datetime.now)

    student = db.relationship('Student', foreign_keys=[student_id])
    resource = db.relationship('Resource', foreign_keys=[resource_id])


class AttendanceRecord(db.Model):
    """每日签到记录：每天每班每学生一条（懒补全 + 登录/心跳实时写入）。

    - 学生登录成功 → upsert 当天记录 status='online'
    - 心跳 → 更新当天记录 last_seen
    - 查看/导出历史时对缺失学生补全 status='offline'
    """
    __tablename__ = 'attendance_record'

    id = db.Column(db.Integer, primary_key=True)
    record_date = db.Column(db.Date, nullable=False, index=True)
    class_id = db.Column(db.Integer, db.ForeignKey('classes.id'), nullable=False, index=True)
    student_id = db.Column(db.Integer, db.ForeignKey('student.id'), nullable=False, index=True)
    name = db.Column(db.String(80), nullable=False)
    status = db.Column(db.String(10), nullable=False, default='offline')  # online/offline
    login_time = db.Column(db.DateTime, nullable=True)
    last_seen = db.Column(db.DateTime, nullable=True)
    seat_number = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.now)

    __table_args__ = (
        db.UniqueConstraint('record_date', 'class_id', 'student_id',
                            name='uq_attendance_date_class_student'),
        db.Index('ix_attendance_date_class', 'record_date', 'class_id'),
    )


class StudentDriveQuota(db.Model):
    """网盘容量覆盖设置：按学生或按班级覆盖全局默认容量（单位 MB）。

    student_id 与 class_id 二选一（各带唯一约束）：
    - 学生级覆盖优先于班级级
    - 班级级覆盖优先于全局默认（SystemConfig: drive_default_quota_mb）
    """
    __tablename__ = 'student_drive_quota'

    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('student.id'),
                           nullable=True, unique=True)
    class_id = db.Column(db.Integer, db.ForeignKey('classes.id'),
                         nullable=True, unique=True)
    quota_mb = db.Column(db.Integer, nullable=False, default=1024)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)


def _decrypt_api_key_or_empty(value, owner):
    """解密 AI Key；SECRET_KEY 被更换导致无法解密时返回 '' 并告警。

    直接抛 ValueError 会让 /api/ai/status、AI 配置页、学生 AI 配置页全部 500
    （管理员连重新录入 Key 的页面都打不开）。返回空串 = 视为未配置，界面
    会提示重新填写，重新保存即用新密钥加密。
    """
    try:
        return decrypt_secret(value)
    except ValueError:
        import logging
        logging.getLogger(__name__).warning(
            '%s 的 AI API Key 无法解密（SECRET_KEY 可能已更换），按未配置处理，请重新录入', owner)
        return ''


class AIConfig(db.Model):
    """AI对话配置表"""
    __tablename__ = 'ai_config'

    id = db.Column(db.Integer, primary_key=True)
    _api_key = db.Column('api_key', db.Text)
    api_url = db.Column(db.String(500))
    model = db.Column(db.String(200))
    # provider: 'openai' = OpenAI 兼容协议, 'anthropic' = Anthropic 原生 /v1/messages
    provider = db.Column(db.String(20), default='openai')
    enabled = db.Column(db.Boolean, default=False)
    # config_mode: 'admin' = 应用控制端配置（学生无需配置）, 'student' = 学生端自行配置
    config_mode = db.Column(db.String(20), default='admin')
    page_context_default = db.Column(db.Boolean, default=True)
    # 教师端 AI：编辑/只读两种教师登录模式共用管理员 API 配置；
    # 单独开关便于管理员只关闭教师端而不影响学生。
    teacher_enabled = db.Column(db.Boolean, default=True)
    teacher_page_context_default = db.Column(db.Boolean, default=True)
    max_tokens = db.Column(db.Integer, default=2048)
    temperature = db.Column(db.Float, default=0.7)
    # 当前对话模型是否支持图片理解（视觉）。开启后前端会把当前页面图片
    # 压缩后随消息发送；不支持视觉的模型应保持关闭，前端会提示图片未发送。
    vision_enabled = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

    @property
    def api_key(self):
        return _decrypt_api_key_or_empty(self._api_key, 'AIConfig')

    @api_key.setter
    def api_key(self, value):
        self._api_key = encrypt_secret(value)


class AIChatMessage(db.Model):
    """AI对话消息表"""
    __tablename__ = 'ai_chat_message'

    id = db.Column(db.Integer, primary_key=True)
    # student_id 可空：管理端/课堂端无学生身份，统一用 actor 标识会话归属
    student_id = db.Column(db.Integer, db.ForeignKey('student.id'), nullable=True)
    # actor: 稳定的会话归属标识 — 'student:<id>' / 'admin' / 'guest:<uuid>'
    actor = db.Column(db.String(50), index=True)
    session_id = db.Column(db.String(50), nullable=False)
    role = db.Column(db.String(20), nullable=False)
    content = db.Column(db.Text)
    page_context = db.Column(db.Text)
    # DeepSeek 文件引用（JSON: [{id,name,purpose}]）：多轮对话继续引用同一文档
    attachments = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.now)

    student = db.relationship('Student', foreign_keys=[student_id])


class StudentAIConfig(db.Model):
    """学生端AI配置表（当 config_mode='student' 时使用）"""
    __tablename__ = 'student_ai_config'

    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('student.id'), nullable=False, unique=True, index=True)
    _api_key = db.Column('api_key', db.Text)
    api_url = db.Column(db.String(500))
    model = db.Column(db.String(200))
    # provider: 'openai' = OpenAI 兼容协议, 'anthropic' = Anthropic 原生 /v1/messages
    provider = db.Column(db.String(20), default='openai')
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

    student = db.relationship('Student', foreign_keys=[student_id])

    @property
    def api_key(self):
        return _decrypt_api_key_or_empty(self._api_key, 'StudentAIConfig')

    @api_key.setter
    def api_key(self, value):
        self._api_key = encrypt_secret(value)


class TeacherAIConfig(db.Model):
    """教师个人 AI 配置（编辑模式可写；只读模式可按开关选用）。"""
    __tablename__ = 'teacher_ai_config'

    id = db.Column(db.Integer, primary_key=True)
    teacher_id = db.Column(db.Integer, db.ForeignKey('teacher.id'), nullable=False,
                           unique=True, index=True)
    _api_key = db.Column('api_key', db.Text)
    api_url = db.Column(db.String(500))
    model = db.Column(db.String(200))
    provider = db.Column(db.String(20), default='openai')
    # 只读模式是否使用本配置（False/旧数据 = 跟随管理员配置）
    readonly_use_own = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

    teacher = db.relationship('Teacher', foreign_keys=[teacher_id])

    @property
    def api_key(self):
        return _decrypt_api_key_or_empty(self._api_key, 'TeacherAIConfig')

    @api_key.setter
    def api_key(self, value):
        self._api_key = encrypt_secret(value)


class TeacherAIShare(db.Model):
    """教师将个人 AI 配置共享给指定任教班级的学生使用。"""
    __tablename__ = 'teacher_ai_share'
    __table_args__ = (
        db.UniqueConstraint('teacher_id', 'class_id',
                            name='uq_teacher_ai_share'),
    )

    id = db.Column(db.Integer, primary_key=True)
    teacher_id = db.Column(db.Integer, db.ForeignKey('teacher.id'),
                           nullable=False, index=True)
    class_id = db.Column(db.Integer, db.ForeignKey('classes.id'),
                         nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.now)


class AIImageConfig(db.Model):
    """生图模型配置（管理端统一配置，教师/学生按开关使用）。"""
    __tablename__ = 'ai_image_config'

    id = db.Column(db.Integer, primary_key=True)
    enabled = db.Column(db.Boolean, default=False)
    # 一期仅 OpenAI Images 兼容协议；后续可扩展 sdwebui/comfyui
    provider = db.Column(db.String(30), default='openai_images')
    api_url = db.Column(db.String(500))
    _api_key = db.Column('api_key', db.Text)
    model = db.Column(db.String(200))
    size = db.Column(db.String(20), default='1024x1024')
    quality = db.Column(db.String(20), default='')
    max_images = db.Column(db.Integer, default=1)
    timeout_seconds = db.Column(db.Integer, default=90)
    allow_student = db.Column(db.Boolean, default=True)
    allow_teacher = db.Column(db.Boolean, default=True)
    # 二期自动判断用；一期仅保存配置
    auto_intent = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

    @property
    def api_key(self):
        return _decrypt_api_key_or_empty(self._api_key, 'AIImageConfig')

    @api_key.setter
    def api_key(self, value):
        self._api_key = encrypt_secret(value)


class AIImage(db.Model):
    """AI 生成图片记录（文件落盘，读取时校验 actor 归属）。"""
    __tablename__ = 'ai_image'

    id = db.Column(db.String(36), primary_key=True)
    actor = db.Column(db.String(80), nullable=False, index=True)
    prompt = db.Column(db.Text)
    prompt_used = db.Column(db.Text)
    model = db.Column(db.String(200))
    size = db.Column(db.String(20))
    file_path = db.Column(db.String(500))
    mime = db.Column(db.String(50))
    created_at = db.Column(db.DateTime, default=datetime.now, index=True)


def migrate_ai_credentials():
    """把数据库中旧版明文 API Key 原地迁移为带版本的密文。"""
    migrated = 0
    for model in (AIConfig, StudentAIConfig, TeacherAIConfig, AIImageConfig):
        for row in model.query.all():
            if row._api_key and not is_encrypted_secret(row._api_key):
                row._api_key = encrypt_secret(row._api_key)
                migrated += 1
    if migrated:
        db.session.commit()
    return migrated


# 数据库迁移版本：跳过条件与写入标记共用此常量。
# 新增表结构变更时：1) 把下方常量递升一版（如 'v5'→'v6'，新迁移逻辑
# 追加在函数末尾标记写入前，全部语句保持幂等）；2) 存量库自动重跑全量
# 检测补新列。
_DB_MIGRATION_VERSION = 'v19'


def _purge_copper_lab_resources():
    """V6.1.0：铜匠实验室外置到 123/，删除旧内置资源及关联数据。

    幂等；按产品确认不做备份。删除顺序与 resources.delete_resource 一致：
    先清无级联子表（测验成绩/教学会话/问卷链/授权），再删资源行
    （ORM 级联活动、作品、评价）。
    """
    import logging

    from sqlalchemy import and_, or_

    log = logging.getLogger(__name__)
    ids = []
    try:
        rows = Resource.query.filter(or_(
            Resource.builtin_key.like('copper_lab%'),
            and_(Resource.creator_name == '系统内置',
                 Resource.url.like('/copper-lab%')),
        )).all()
        if not rows:
            return 0
        ids = [r.id for r in rows]
        log.warning('V6.1.0 外置迁移：删除铜匠实验室资源 %s', ids)
        ResourceQuizResult.query.filter(
            ResourceQuizResult.resource_id.in_(ids)).delete(
                synchronize_session=False)
        TeachingSession.query.filter(
            TeachingSession.resource_id.in_(ids)).delete(
                synchronize_session=False)
        survey_ids = [row[0] for row in db.session.query(Survey.id).filter(
            Survey.resource_id.in_(ids)).all()]
        if survey_ids:
            SurveyAnswer.query.filter(
                SurveyAnswer.survey_id.in_(survey_ids)).delete(
                    synchronize_session=False)
            SurveyQuestion.query.filter(
                SurveyQuestion.survey_id.in_(survey_ids)).delete(
                    synchronize_session=False)
            Survey.query.filter(Survey.id.in_(survey_ids)).delete(
                synchronize_session=False)
        db.session.execute(resource_share.delete().where(
            resource_share.c.resource_id.in_(ids)))
        db.session.execute(resource_audience.delete().where(
            resource_audience.c.resource_id.in_(ids)))
        for res in rows:
            db.session.delete(res)
        db.session.commit()
        return len(ids)
    except Exception:
        db.session.rollback()
        log.warning('铜匠实验室资源删除失败（已隐藏，下次启动重试）',
                    exc_info=True)
        if ids:
            try:
                Resource.query.filter(Resource.id.in_(ids)).update(
                    {'show_in_student': False, 'show_in_classroom': False},
                    synchronize_session=False)
                db.session.commit()
            except Exception:
                db.session.rollback()
        return 0


def migrate_db():
    """数据库迁移 — 为已有表添加新列（如果不存在）

    使用 PostgreSQL information_schema.columns 检测表结构。
    db.create_all() 已创建初始表，本函数处理后续新增的列。
    """
    import logging
    _log = logging.getLogger(__name__)
    # 迁移完成标记：全量检测执行过则跳过——每次启动 5-15s 的
    # information_schema 数十次元数据查询不再重复。
    # 版本约定：跳过条件与写入标记都引用 _DB_MIGRATION_VERSION 常量——
    # 新增表结构变更时把常量升为 'v2' 并在本函数末尾（标记写入前）追加
    # 新迁移逻辑；存量库标记不匹配常量时自动全量重跑（全部迁移语句幂等）。
    try:
        if SystemConfig.get('db_migration_version') == _DB_MIGRATION_VERSION:
            return
    except Exception:
        pass  # 配置表不可用时仍执行检测
    # 动态取当前 schema，不再硬编码 'public'，兼容非默认 schema 部署
    try:
        _schema_name = str(db.session.execute(
            text('SELECT current_schema()')
        ).scalar() or 'public')
    except Exception:
        _schema_name = 'public'
    _schema_sql = _quote_sql_identifier(_schema_name)
    # 允许失败的兼容迁移（唯一约束/索引等）失败时记录在此：只要有失败就
    # 不写版本标记，下次启动重试——否则一次数据冲突会让该迁移永久跳过，
    # schema 再也无法自愈。
    _optional_failures = []

    def _get_cols(table_name):
        """查询 PostgreSQL information_schema 获取表的所有列名"""
        result = db.session.execute(text(
            "SELECT column_name FROM information_schema.columns"
            " WHERE table_name = :tbl AND table_schema = :schema"
        ), {'tbl': table_name, 'schema': _schema_name})
        return {row[0] for row in result}

    def _table_exists(table_name):
        """检查当前 schema 下的表是否存在，避免 ALTER 缺失表污染事务。"""
        result = db.session.execute(text(
            "SELECT 1 FROM information_schema.tables"
            " WHERE table_name = :tbl AND table_schema = :schema"
            " LIMIT 1"
        ), {'tbl': table_name, 'schema': _schema_name})
        return result.first() is not None

    def _add_cols(table_name, columns):
        """批量为表添加缺失的列"""
        try:
            table_sql = _quote_sql_identifier(table_name)
        except ValueError:
            _log.warning('跳过非法表名: %s', table_name)
            return
        try:
            if not _table_exists(table_name):
                _log.debug('表 %s 不存在，跳过兼容列迁移', table_name)
                return
            existing = _get_cols(table_name)
        except Exception:
            if not db.session.is_active:
                db.session.rollback()
            _log.debug('读取表 %s 结构失败，跳过兼容列迁移', table_name, exc_info=True)
            return
        for col_name, col_def in columns.items():
            if col_name not in existing:
                try:
                    col_sql = _quote_sql_identifier(col_name)
                    with db.session.begin_nested():
                        db.session.execute(text(
                            f'ALTER TABLE {table_sql} ADD COLUMN IF NOT EXISTS {col_sql} {col_def};'
                        ))
                except Exception:
                    if not db.session.is_active:
                        db.session.rollback()
                    _log.warning(
                        '迁移列失败，已跳过: %s.%s',
                        table_name, col_name, exc_info=True
                    )

    def _run_optional(sql, message):
        """执行允许失败的兼容迁移，失败时回滚 savepoint，不污染外层事务。"""
        try:
            with db.session.begin_nested():
                db.session.execute(text(sql))
            return True
        except Exception:
            if not db.session.is_active:
                db.session.rollback()
            _optional_failures.append(message)
            _log.debug('%s，跳过', message, exc_info=True)
            return False

    def _constraint_exists(table_name, constraint_name):
        try:
            with db.session.begin_nested():
                result = db.session.execute(text(
                    "SELECT 1 FROM pg_constraint con"
                    " JOIN pg_class cls ON cls.oid = con.conrelid"
                    " JOIN pg_namespace nsp ON nsp.oid = cls.relnamespace"
                    " WHERE nsp.nspname = :schema"
                    " AND cls.relname = :table_name"
                    " AND con.conname = :constraint_name"
                    " LIMIT 1"
                ), {'schema': _schema_name,
                    'table_name': table_name, 'constraint_name': constraint_name})
                return result.first() is not None
        except Exception:
            if not db.session.is_active:
                db.session.rollback()
            _log.debug('约束存在性检查失败，按不存在处理', exc_info=True)
            return False

    def _drop_fk_to(table_name, ref_table, col_name):
        """删除表中指向指定表/列的 FK 约束（按 pg_constraint 动态定位）。

        用于修正历史外键设计错误：Homework.teacher_id / * .graded_by
        曾错误声明为 REFERENCES student(id)，使教师 ID 无法写入。
        列本身保留为普通 INTEGER。
        """
        try:
            with db.session.begin_nested():
                rows = db.session.execute(text(
                    "SELECT con.conname FROM pg_constraint con"
                    " JOIN pg_class cls ON cls.oid = con.conrelid"
                    " JOIN pg_namespace nsp ON nsp.oid = cls.relnamespace"
                    " JOIN pg_class ref ON ref.oid = con.confrelid"
                    " WHERE nsp.nspname = :schema AND con.contype = 'f'"
                    " AND cls.relname = :tbl AND ref.relname = :ref"
                    " AND EXISTS (SELECT 1 FROM unnest(con.conkey) k"
                    "             JOIN pg_attribute a ON a.attrelid = cls.oid"
                    "              AND a.attnum = k"
                    "             WHERE a.attname = :col)"
                ), {'schema': _schema_name, 'tbl': table_name,
                    'ref': ref_table, 'col': col_name}).all()
                tbl_sql = _quote_sql_identifier(table_name)
                for (con_name,) in rows:
                    db.session.execute(text(
                        f'ALTER TABLE {tbl_sql} DROP CONSTRAINT '
                        f'{_quote_sql_identifier(con_name)}'
                    ))
                    _log.info('已删除外键约束 %s.%s（指向 %s.%s）',
                              table_name, con_name, ref_table, col_name)
            return True
        except Exception:
            if not db.session.is_active:
                db.session.rollback()
            _log.debug('删除外键约束失败，已跳过: %s.%s', table_name, col_name, exc_info=True)
            return False

    try:
        # 历史外键设计错误清理：teacher_id / graded_by 曾错误指向 student 表。
        # 这些 FK 使教师 ID 无法写入，作业创建者/批改者信息长期丢失。
        # 列保留为普通 INTEGER（语义为 Teacher.id），仅在约束存在时删除。
        _drop_fk_to('homework', 'student', 'teacher_id')
        _drop_fk_to('homework_submission', 'student', 'graded_by')
        _drop_fk_to('python_answer', 'student', 'graded_by')

        # student 表
        _add_cols('student', {
            'student_number': 'VARCHAR(50)',
            'password_hash': 'VARCHAR(256)',
            'grade': 'VARCHAR(20)',
            'is_activated': 'BOOLEAN DEFAULT TRUE',
            'has_changed_password': 'BOOLEAN DEFAULT FALSE',
            'class_id': 'INTEGER REFERENCES classes(id)',
            'group_id': 'INTEGER REFERENCES study_group(id)',
            'last_seen': 'TIMESTAMP',
        })
        _run_optional(
            'ALTER TABLE student DROP COLUMN IF EXISTS plain_password;',
            'student.plain_password 已删除或表尚未创建'
        )

        # teacher 表
        _add_cols('teacher', {
            'display_name': 'VARCHAR(80)',
            'is_active': 'BOOLEAN DEFAULT TRUE',
            'created_at': 'TIMESTAMP',
            'last_login_at': 'TIMESTAMP',
        })

        # classroom_setting 表
        _add_cols('classroom_setting', {
            'seat_offset': 'INTEGER DEFAULT 0',
            'auto_switch': 'BOOLEAN DEFAULT FALSE',
        })

        # group_file 表
        _add_cols('group_file', {
            'file_path': 'VARCHAR(500)',
            'pptist_json': 'TEXT',
        })

        # student_drive_file 表（个人网盘 PPTist 编辑支持）
        _add_cols('student_drive_file', {
            'pptist_json': 'TEXT',
        })

        # study_group 表
        _add_cols('study_group', {
            'slogan': 'VARCHAR(100)',
            'icon': 'VARCHAR(50)',
            'drive_enabled': 'BOOLEAN DEFAULT TRUE',
            'upload_enabled': 'BOOLEAN DEFAULT TRUE',
            'max_space_mb': 'INTEGER DEFAULT 50',
        })

        # resource 表
        _add_cols('resource', {
            'homework_files': 'TEXT',
            'file_permissions': 'TEXT',
            'show_in_student': 'BOOLEAN DEFAULT TRUE',
            'show_in_classroom': 'BOOLEAN DEFAULT TRUE',
            'quiz_mode': 'VARCHAR(20) DEFAULT \'inject\'',
            'injected': 'BOOLEAN DEFAULT FALSE',
            'backup_path': 'VARCHAR(500)',
            'lesson_tree': 'TEXT',
        })

        # resource / exam 表 — subject_id 外键
        for table in ['resource', 'exam']:
            _add_cols(table, {
                'subject_id': 'INTEGER REFERENCES subject(id)',
            })

        # exam 表
        _add_cols('exam', {
            'is_visible': 'BOOLEAN DEFAULT TRUE',
            'is_enabled': 'BOOLEAN DEFAULT TRUE',
            'is_collected': 'BOOLEAN DEFAULT FALSE',
            'allow_view_results': 'BOOLEAN DEFAULT TRUE',
            'duration': 'INTEGER',
        })

        # sub_question 表
        _add_cols('sub_question', {
            'image_url': 'TEXT',
        })

        # question 表
        _add_cols('question', {
            'footer_content': 'TEXT',
        })

        # result 表（开放式试题批改系统）
        _add_cols('result', {
            'grading_status': "VARCHAR(20) DEFAULT 'auto_graded'",
            'manual_scores': 'TEXT',
            'graded_by': 'INTEGER',
            'graded_at': 'TIMESTAMP',
        })

        # result 表 — 添加唯一约束防止重复提交（幂等安全）
        try:
            if not _constraint_exists('result', 'uq_result_student_exam'):
                _run_optional(
                    'ALTER TABLE result ADD CONSTRAINT uq_result_student_exam'
                    ' UNIQUE (student_id, exam_id);',
                    'result 表唯一约束 uq_result_student_exam 可能已存在或存在重复数据'
                )
        except Exception:
            _log.debug('result 表唯一约束可能已存在，跳过', exc_info=True)

        # homework_submission 表 — 唯一约束防止重复提交（先清理存量重复，
        # 保留每人最新一次提交，再添加约束，幂等安全）
        try:
            if not _constraint_exists('homework_submission', 'uq_homework_submission_student'):
                _run_optional(
                    'DELETE FROM homework_submission hs USING homework_submission hs2'
                    ' WHERE hs.id < hs2.id'
                    ' AND hs.homework_id = hs2.homework_id'
                    ' AND hs.student_id = hs2.student_id;',
                    'homework_submission 重复数据清理可能已执行'
                )
                _run_optional(
                    'ALTER TABLE homework_submission ADD CONSTRAINT'
                    ' uq_homework_submission_student UNIQUE (homework_id, student_id);',
                    'homework_submission 唯一约束可能已存在或仍有重复数据'
                )
        except Exception:
            _log.debug('homework_submission 唯一约束可能已存在，跳过', exc_info=True)

        # resource_quiz_result 表 — 学生×资源唯一约束（先清理存量重复，
        # 保留每人每资源最新一条，再添加约束，幂等安全）
        try:
            if not _constraint_exists('resource_quiz_result', 'uq_resource_quiz_student'):
                _run_optional(
                    'DELETE FROM resource_quiz_result r USING resource_quiz_result r2'
                    ' WHERE r.id < r2.id'
                    ' AND r.student_id = r2.student_id'
                    ' AND r.resource_id = r2.resource_id;',
                    'resource_quiz_result 重复数据清理可能已执行'
                )
                _run_optional(
                    'ALTER TABLE resource_quiz_result ADD CONSTRAINT'
                    ' uq_resource_quiz_student UNIQUE (student_id, resource_id);',
                    'resource_quiz_result 唯一约束可能已存在'
                )
        except Exception:
            _log.debug('resource_quiz_result 唯一约束可能已存在，跳过', exc_info=True)

        # python_answer 表 — 学生×题目唯一约束（并发上传会产生同一学生同一题的
        # 重复答案行，评分/批改 filter_by().first() 任取一行，成绩/文件/状态
        # 互相不一致。先清理存量重复（保留每人每题最新一条），再添加约束，幂等安全）
        try:
            if not _constraint_exists('python_answer', 'uq_python_answer_student_question'):
                _run_optional(
                    'DELETE FROM python_answer pa USING python_answer pa2'
                    ' WHERE pa.id < pa2.id'
                    ' AND pa.question_id = pa2.question_id'
                    ' AND pa.student_id = pa2.student_id;',
                    'python_answer 重复数据清理可能已执行'
                )
                _run_optional(
                    'ALTER TABLE python_answer ADD CONSTRAINT'
                    ' uq_python_answer_student_question'
                    ' UNIQUE (question_id, student_id);',
                    'python_answer 唯一约束可能已存在或仍有重复数据'
                )
        except Exception:
            _log.debug('python_answer 唯一约束可能已存在，跳过', exc_info=True)

        # student 表 — 学号全局唯一约束（登录身份唯一性；迁移前检查存量重复，
        # 有重复则跳过并告警，避免迁移失败，由管理员清理后重试）
        # 存量空学号 '' → NULL（此前编辑分支以 '' 入库，uq_student_number
        # 把多个空串视为同一值 → 清空学号后编辑其他空学号学生必 500；
        # 与添加分支的 NULL 语义对齐后解除存量冲突。幂等安全）
        try:
            _run_optional(
                "UPDATE student SET student_number = NULL"
                " WHERE student_number = '';",
                'student 空学号清理可能已执行'
            )
        except Exception:
            _log.debug('student 空学号清理失败（跳过）', exc_info=True)

        try:
            if not _constraint_exists('student', 'uq_student_number'):
                dup = db.session.execute(text(
                    'SELECT student_number FROM student'
                    ' GROUP BY student_number HAVING COUNT(*) > 1 LIMIT 1'
                )).fetchone()
                if dup:
                    _log.warning(
                        '存在重复学号 %s，跳过学号唯一约束创建（请先清理重复数据）',
                        dup[0])
                else:
                    _run_optional(
                        'ALTER TABLE student ADD CONSTRAINT'
                        ' uq_student_number UNIQUE (student_number);',
                        'student 学号唯一约束可能已存在'
                    )
        except Exception:
            _log.debug('student 学号唯一约束可能已存在，跳过', exc_info=True)

        # exam 表 — 试卷名全局唯一约束（应用层查重 + 批量导入按卷名避让
        # 依赖此约定；存量重名自动追加「（id）」后缀改名保留数据后建约束，
        # 幂等安全，约束已存在/仍有重名时跳过）
        try:
            _run_optional(
                "UPDATE exam SET name = LEFT(name, 90) || '（' || id || '）'"
                " WHERE id IN (SELECT id FROM (SELECT id,"
                " ROW_NUMBER() OVER (PARTITION BY name ORDER BY id) AS rn"
                " FROM exam) t WHERE rn > 1);",
                'exam 重名清理可能已执行'
            )
            if not _constraint_exists('exam', 'uq_exam_name'):
                _run_optional(
                    'ALTER TABLE exam ADD CONSTRAINT'
                    ' uq_exam_name UNIQUE (name);',
                    'exam 名称唯一约束可能已存在'
                )
        except Exception:
            _log.debug('exam 名称唯一约束创建跳过', exc_info=True)

        # question/exam 解耦（V5.0.2）：题目归属迁移至 exam_question 中间表。
        # 存量库：从 question.exam_id 回填历史归属（幂等，position=原 id 序），
        # exam_id 降级为可空"创建来源卷"（新库由模型 nullable 直接生效）
        try:
            _run_optional(
                'INSERT INTO exam_question (exam_id, question_id, position)'
                ' SELECT q.exam_id, q.id,'
                ' ROW_NUMBER() OVER (PARTITION BY q.exam_id ORDER BY q.id)'
                ' FROM question q WHERE q.exam_id IS NOT NULL'
                ' AND NOT EXISTS (SELECT 1 FROM exam_question eq'
                '   WHERE eq.exam_id = q.exam_id'
                '   AND eq.question_id = q.id);',
                'exam_question 历史归属可能已回填'
            )
        except Exception:
            _log.debug('exam_question 历史归属回填跳过', exc_info=True)
        try:
            _run_optional(
                'ALTER TABLE question ALTER COLUMN exam_id DROP NOT NULL;',
                'question.exam_id 可能已可空'
            )
        except Exception:
            _log.debug('question.exam_id 放宽可空跳过', exc_info=True)

        # ai_config 表 — 新增配置模式字段
        _add_cols('ai_config', {
            'config_mode': "VARCHAR(20) DEFAULT 'admin'",
            'page_context_default': 'BOOLEAN DEFAULT TRUE',
            'teacher_enabled': 'BOOLEAN DEFAULT TRUE',
            'teacher_page_context_default': 'BOOLEAN DEFAULT TRUE',
            'max_tokens': 'INTEGER DEFAULT 2048',
            'temperature': 'FLOAT DEFAULT 0.7',
            'provider': "VARCHAR(20) DEFAULT 'openai'",
            'vision_enabled': 'BOOLEAN DEFAULT FALSE',
        })

        # student_ai_config 表 — 新增供应商字段
        _add_cols('student_ai_config', {
            'provider': "VARCHAR(20) DEFAULT 'openai'",
        })
        # Fernet 密文长度大于旧 VARCHAR(500)，统一改为无损 TEXT。
        _run_optional(
            'ALTER TABLE ai_config ALTER COLUMN api_key TYPE TEXT;',
            'ai_config.api_key 已为 TEXT 或表尚未创建'
        )
        _run_optional(
            'ALTER TABLE student_ai_config ALTER COLUMN api_key TYPE TEXT;',
            'student_ai_config.api_key 已为 TEXT 或表尚未创建'
        )

        # ai_chat_message 表 — 多身份会话归属（管理端/课堂端无 student_id）
        _add_cols('ai_chat_message', {
            'actor': 'VARCHAR(50)',
        })
        # student_id 放开 NOT NULL，允许非学生身份（admin/guest）写入
        _run_optional(
            'ALTER TABLE ai_chat_message ALTER COLUMN student_id DROP NOT NULL;',
            'ai_chat_message.student_id DROP NOT NULL 可能已执行'
        )
        # 回填存量数据的 actor：历史消息均为学生产生
        _run_optional(
            "UPDATE ai_chat_message SET actor = 'student:' || student_id"
            " WHERE actor IS NULL AND student_id IS NOT NULL;",
            'ai_chat_message.actor 回填可能已执行'
        )
        _run_optional(
            'CREATE INDEX IF NOT EXISTS ix_ai_chat_message_actor'
            ' ON ai_chat_message (actor);',
            'ai_chat_message.actor 索引可能已存在'
        )

        # student_drive_file 表
        _add_cols('student_drive_file', {
            'sender_type': "VARCHAR(20) DEFAULT 'teacher'",
            'sender_id': 'INTEGER',
            'sender_name': 'VARCHAR(80)',
            'source_type': "VARCHAR(30) DEFAULT 'manual'",
            'source_id': 'INTEGER',
            'note': 'VARCHAR(500)',
            'created_at': 'TIMESTAMP',
        })

        # learning_activity 表
        _add_cols('learning_activity', {
            'document_name': 'VARCHAR(255)',
            'upload_type': "VARCHAR(20) DEFAULT 'file'",
            'sort_order': 'INTEGER DEFAULT 0',
            'is_active': 'BOOLEAN DEFAULT TRUE',
            'updated_at': 'TIMESTAMP',
            'start_time': 'TIMESTAMP',
            'end_time': 'TIMESTAMP',
            'capacity': 'INTEGER',
        })

        # student_work 表
        _add_cols('student_work', {
            'work_type': "VARCHAR(20) DEFAULT 'file'",
            'file_size': 'INTEGER DEFAULT 0',
            'status': "VARCHAR(20) DEFAULT 'submitted'",
            'public_token': 'VARCHAR(64)',
            'is_excellent': 'BOOLEAN DEFAULT FALSE',
        })

        # work_evaluation 表
        _add_cols('work_evaluation', {
            'grade': 'VARCHAR(20)',
            'evaluated_by': 'VARCHAR(80)',
            'evaluated_at': 'TIMESTAMP',
        })

        # teaching_session 表
        _add_cols('teaching_session', {
            'teacher_id': 'INTEGER REFERENCES teacher(id)',
            'duration_minutes': 'INTEGER',
            'attendance_snapshot': 'TEXT',
            'status': "VARCHAR(20) DEFAULT 'active'",
        })

        # student_drive_quota 表 — 网盘容量覆盖设置
        _run_optional(
            'CREATE TABLE IF NOT EXISTS student_drive_quota ('
            ' id SERIAL PRIMARY KEY,'
            ' student_id INTEGER UNIQUE REFERENCES student(id),'
            ' class_id INTEGER UNIQUE REFERENCES classes(id),'
            ' quota_mb INTEGER NOT NULL DEFAULT 1024,'
            ' updated_at TIMESTAMP);',
            'student_drive_quota 表可能已存在'
        )

        # attendance_record 表 — 每日签到记录
        _run_optional(
            'CREATE TABLE IF NOT EXISTS attendance_record ('
            ' id SERIAL PRIMARY KEY,'
            ' record_date DATE NOT NULL,'
            ' class_id INTEGER NOT NULL REFERENCES classes(id),'
            ' student_id INTEGER NOT NULL REFERENCES student(id),'
            ' name VARCHAR(80) NOT NULL,'
            ' status VARCHAR(10) NOT NULL DEFAULT \'offline\','
            ' login_time TIMESTAMP,'
            ' last_seen TIMESTAMP,'
            ' seat_number INTEGER,'
            ' created_at TIMESTAMP,'
            ' CONSTRAINT uq_attendance_date_class_student'
            ' UNIQUE (record_date, class_id, student_id));'
            'CREATE INDEX IF NOT EXISTS ix_attendance_date_class'
            ' ON attendance_record (record_date, class_id);',
            'attendance_record 表可能已存在'
        )

        # 系统开关默认值（含网盘配额与自动清理配置）
        default_configs = {
            'class_buttons_enabled': 'true',
            'student_access_enabled': 'true',
            'admin_remote_enabled': 'false',   # 远程管理员登录默认关闭（本机访问不受影响）
            'drive_default_quota_mb': '20',        # 全局默认网盘容量（MB），初始 20MB 防撑爆存储
            'drive_cleanup_enabled': 'false',      # 网盘自动清理开关
            'drive_cleanup_idle_days': '90',       # 闲置 N 天自动清理
            'drive_cleanup_interval_hours': '24',  # 清理检查周期（小时）
            'attendance_time_window': '07:00-22:00',  # 考勤签到时间窗（HH:MM-HH:MM），窗外登录不计为"窗口内到课"
            'ai_message_cleanup_enabled': 'true',    # AI 对话消息定期归档清理开关
            'ai_message_retention_days': '180',      # 保留 N 天前的对话消息
            'ai_message_cleanup_interval_hours': '24',  # 清理检查周期（小时）
        }
        for key, value in default_configs.items():
            if not SystemConfig.query.filter_by(key=key).first():
                db.session.add(SystemConfig(key=key, value=value))

        # 插入默认学科
        if not Subject.query.filter_by(name='高中信息科技').first():
            db.session.add(Subject(name='高中信息科技', sort_order=1))

        # ── v2：资源测验结果扩展字段（客户端自报等级/答对题数）──
        # 覆盖纯等级测验（无分数）与"答对题数/总题数"式测验的记录需求
        _add_cols('resource_quiz_result', {
            'grade': 'VARCHAR(20)',
            'correct_count': 'INTEGER',
            'question_count': 'INTEGER',
        })

        # ── v5：课堂章节树（在线课堂式资源学习界面 /study/lesson/<id>）──
        # JSON Text：[{id,title,type:'section',children:[...],items:[{id,title,kind,src,doc_category,visible,activity_id}]}]
        _add_cols('resource', {
            'lesson_tree': 'TEXT',
        })

        # ── v6：教师资源归属与只读共享 ──
        # 新关联表由 db.create_all() 创建；存量资源一律视为管理员创建、
        # 默认不共享（管理员升级后按需授权）。
        _add_cols('resource', {
            'creator_teacher_id': 'INTEGER REFERENCES teacher(id)',
            'creator_type': "VARCHAR(20) DEFAULT 'admin'",
            'creator_name': 'VARCHAR(80)',
        })
        _run_optional(
            "UPDATE resource SET creator_type='admin' "
            "WHERE creator_type IS NULL OR creator_type=''",
            '回填资源创建者类型')

        # ── v7：教师年级/任课班级 ──
        _add_cols('teacher', {'grade': 'VARCHAR(50)'})

        # ── v8：多班课堂会话 ──
        _add_cols('teaching_session', {'class_id': 'INTEGER REFERENCES classes(id)'})
        _run_optional(
            'ALTER TABLE class_schedule DROP CONSTRAINT IF EXISTS uq_cs_weekday_period',
            '移除旧单班课程表唯一约束')
        _run_optional(
            'CREATE UNIQUE INDEX IF NOT EXISTS uq_cs_weekday_period_class '
            'ON class_schedule(weekday, period_number, class_name)',
            '创建多班课程表唯一索引')

        # ── v11：注入前检测 + 多 HTML 测验成绩隔离 ──
        _add_cols('resource', {
            'quiz_pending_files': 'TEXT',
            'quiz_inject_state': "VARCHAR(20) DEFAULT 'none'",
        })
        _run_optional(
            "UPDATE resource SET quiz_inject_state='verified' "
            "WHERE injected IS TRUE AND (quiz_inject_state IS NULL "
            "OR quiz_inject_state='none')",
            '回填已注入资源状态')
        _add_cols('resource_quiz_result', {
            'source_file': 'VARCHAR(500)',
            'quiz_key': "VARCHAR(120) NOT NULL DEFAULT 'legacy'",
            'adapter_version': 'INTEGER',
        })
        _run_optional(
            "UPDATE resource_quiz_result SET quiz_key='legacy' "
            "WHERE quiz_key IS NULL OR quiz_key=''",
            '回填历史成绩 quiz_key')
        _run_optional(
            'ALTER TABLE resource_quiz_result '
            'DROP CONSTRAINT IF EXISTS uq_resource_quiz_student',
            '移除旧单文件成绩唯一约束')
        _run_optional(
            'CREATE UNIQUE INDEX IF NOT EXISTS uq_resource_quiz_student_file '
            'ON resource_quiz_result(student_id, resource_id, quiz_key)',
            '创建多文件成绩唯一索引')

        # ── v12：公开资源 + 调查问卷模块 ──
        # survey/survey_question/survey_answer 为新表，由 db.create_all()
        # 直接建（含声明式索引与唯一约束），此处只需为存量 resource 加列。
        _add_cols('resource', {
            'is_public': 'BOOLEAN DEFAULT FALSE',
        })

        # ── v13：内置资源标记（管理员可编辑/停用，种子不再复活）──
        # resource_audience 为新表（年级×学科授权），由 db.create_all() 建；
        # 存量内置资源的授权范围由启动种子 ensure_chem_lab_resource()
        # 幂等补齐（默认不限年级/不限学科，保持升级前全体可用）。
        _add_cols('resource', {
            'is_builtin': 'BOOLEAN DEFAULT FALSE',
            'builtin_key': 'VARCHAR(64)',
        })

        # ── v14：逐题题干/选项/标准答案，旧 answers 继续兼容历史 SDK ──
        _add_cols('resource_quiz_result', {'question_details': 'TEXT'})

        # ── v18：允许打开页面相关链接（不改变文件列表展示状态）──
        # 提前加列：后续迁移步骤（如 v15 清理）会通过 ORM 查询 Resource，
        # 模型已包含该列，必须先补列否则存量库迁移时报 UndefinedColumn。
        _add_cols('resource', {
            'allow_related_files': 'BOOLEAN DEFAULT FALSE',
        })

        # ── v15：铜匠实验室外置（删除内置资源与关联数据）──
        _purge_copper_lab_resources()

        # ── v16：教师 AI 只读来源；班级共享表由 create_all 建 ──
        _add_cols('teacher_ai_config', {
            'readonly_use_own': 'BOOLEAN DEFAULT FALSE',
        })

        # ── v17：DeepSeek 文件输入的多轮引用（JSON 附件列表）──
        _add_cols('ai_chat_message', {
            'attachments': 'TEXT',
        })

        # ── v19：账号登录会话/页面轨迹表由 db.create_all() 创建 ──
        # account_session / account_page_view 为新增表，无存量列迁移。

        db.session.commit()
        # 全量迁移完成：仅全部可选迁移也成功时写版本标记（下次启动跳过）；
        # 有失败项则保留旧标记，下次启动重试，避免 schema 永久停在半迁移状态
        if _optional_failures:
            _log.warning(
                '部分兼容迁移失败（%d 项），本次不写入版本标记，下次启动重试: %s',
                len(_optional_failures), _optional_failures[:5])
        else:
            try:
                SystemConfig.set('db_migration_version', _DB_MIGRATION_VERSION)
                db.session.commit()
            except Exception:
                _log.debug('db_migration_version 标记写入失败（跳过，下次启动重测）',
                           exc_info=True)
    except Exception:
        db.session.rollback()
        raise


def create_db_indexes():
    """创建数据库索引以提高查询性能"""
    try:
        db.session.execute(text('CREATE INDEX IF NOT EXISTS idx_study_group_class_id ON study_group(class_id);'))
        db.session.execute(text('CREATE INDEX IF NOT EXISTS idx_question_exam_id ON question(exam_id);'))
        db.session.execute(text('CREATE INDEX IF NOT EXISTS idx_subquestion_question_id ON sub_question(question_id);'))
        db.session.execute(text('CREATE INDEX IF NOT EXISTS idx_python_answer_question_id ON python_answer(question_id);'))
        db.session.execute(text('CREATE INDEX IF NOT EXISTS idx_python_answer_student_id ON python_answer(student_id);'))
        # Python 试题文件按题目反查（考试提交判分热路径逐题 filter_by(question_id)）
        db.session.execute(text('CREATE INDEX IF NOT EXISTS idx_python_file_question_id ON python_file(question_id);'))
        db.session.execute(text('CREATE INDEX IF NOT EXISTS idx_schedule_sort ON schedule(sort_order);'))
        db.session.execute(text('CREATE INDEX IF NOT EXISTS idx_schedule_is_active ON schedule(is_active);'))
        db.session.execute(text('CREATE INDEX IF NOT EXISTS idx_resource_subject_id ON resource(subject_id);'))
        db.session.execute(text('CREATE INDEX IF NOT EXISTS ix_resource_creator_teacher_id ON resource(creator_teacher_id);'))
        db.session.execute(text('CREATE INDEX IF NOT EXISTS idx_teacher_subject_subject ON teacher_subject(subject_id);'))
        db.session.execute(text('CREATE INDEX IF NOT EXISTS idx_resource_share_teacher ON resource_share(teacher_id);'))
        db.session.execute(text('CREATE INDEX IF NOT EXISTS idx_teacher_class_class ON teacher_class(class_id);'))
        db.session.execute(text('CREATE INDEX IF NOT EXISTS idx_teacher_grade ON teacher(grade);'))
        db.session.execute(text('CREATE INDEX IF NOT EXISTS idx_classroom_session_active ON classroom_session(is_active);'))
        db.session.execute(text('CREATE INDEX IF NOT EXISTS idx_teaching_session_class ON teaching_session(class_id);'))
        db.session.execute(text('CREATE INDEX IF NOT EXISTS idx_group_file_group_id ON group_file(group_id);'))
        db.session.execute(text('CREATE INDEX IF NOT EXISTS idx_appeal_is_read ON appeal(is_read);'))
        db.session.execute(text('CREATE INDEX IF NOT EXISTS idx_resource_quiz_result_student ON resource_quiz_result(student_id);'))
        db.session.execute(text('CREATE INDEX IF NOT EXISTS idx_resource_quiz_result_resource ON resource_quiz_result(resource_id);'))
        db.session.execute(text('CREATE INDEX IF NOT EXISTS idx_ai_chat_message_session ON ai_chat_message(session_id);'))
        db.session.execute(text('CREATE INDEX IF NOT EXISTS idx_ai_chat_message_created ON ai_chat_message(created_at);'))
        db.session.execute(text('CREATE INDEX IF NOT EXISTS idx_student_drive_source ON student_drive_file(source_type, source_id);'))
        # 教师数据边界过滤列（homework.teacher_id = X OR IS NULL 每页过滤）
        db.session.execute(text('CREATE INDEX IF NOT EXISTS idx_homework_teacher_id ON homework(teacher_id);'))
        # 学生「今日学习」待交作业聚合：按启用状态 + 截止时间过滤
        db.session.execute(text('CREATE INDEX IF NOT EXISTS idx_homework_active_deadline ON homework(is_active, deadline);'))
        # 批改中心按 (exam_id, grading_status) 分组统计
        db.session.execute(text('CREATE INDEX IF NOT EXISTS idx_result_exam_grading ON result(exam_id, grading_status);'))
        # 资源测验唯一约束的查询路径（部分存量库无此约束）
        db.session.execute(text('CREATE INDEX IF NOT EXISTS idx_resource_quiz_student_resource ON resource_quiz_result(student_id, resource_id);'))
        # Python 答案文件路径反查（静态目录鉴权钩子每请求一次）
        db.session.execute(text('CREATE INDEX IF NOT EXISTS idx_python_answer_file_path ON python_answer(file_path);'))
        # ── 声明式索引的 raw 兜底（create_all 的固有局限）──
        # db.create_all() 对**已存在**的表完全跳过，不会补建模型里 index=True
        # 声明出来的 ix_* 索引；而本项目表是先于声明存在的（没有 Alembic 迁移
        # 步骤，schema 全靠 create_all + 本节 raw DDL）。后果：**只加 index=True
        # 等于没加**——2026-09-13 实测 pg_indexes，下面几条声明了却从未建出。
        # 命名沿用 SQLAlchemy 的 ix_* 约定，全新库由 create_all 建同名索引，
        # 此处为 no-op（不会产生 B4 那种重复索引）。
        db.session.execute(text('CREATE INDEX IF NOT EXISTS ix_group_join_request_student_id ON group_join_request(student_id);'))
        db.session.execute(text('CREATE INDEX IF NOT EXISTS ix_group_join_request_group_id ON group_join_request(group_id);'))
        db.session.execute(text('CREATE INDEX IF NOT EXISTS ix_appeal_student_id ON appeal(student_id);'))
        # 复合索引：LearningActivity.__table_args__ 的注释声称它覆盖 resources.py
        # 按 (resource_id, is_active) 的过滤，实际存量库上从未建出（只有两个单列索引）
        db.session.execute(text('CREATE INDEX IF NOT EXISTS ix_learning_activity_resource_active ON learning_activity(resource_id, is_active);'))
        # 题型过滤（api_exams 外链卷判定，无 exam_id 锚点）
        db.session.execute(text('CREATE INDEX IF NOT EXISTS ix_question_question_type ON question(question_type);'))
        # FK 列的单列索引（按学生批量删的 .in_(student_ids) 路径）
        db.session.execute(text('CREATE INDEX IF NOT EXISTS ix_study_group_leader_id ON study_group(leader_id);'))
        db.session.execute(text('CREATE INDEX IF NOT EXISTS ix_group_file_uploader_id ON group_file(uploader_id);'))
        # 关联表按 class_id 单列过滤（复合主键最左前缀用不上）
        db.session.execute(text('CREATE INDEX IF NOT EXISTS ix_homework_classes_class_id ON homework_classes(class_id);'))
        # ── 模糊搜索（ILIKE %keyword%）──
        # B-tree 索引对前导通配符无效；pg_trgm GIN 索引可支撑学生姓名/学号/
        # 班级、题目内容、作业标题等 contains() 搜索（数据量上万后仍走索引）。
        # gin_trgm_ops 操作符类依赖 pg_trgm 扩展。先提交上面已建的全部
        # B-tree 索引，再单独建 GIN：此前 CREATE EXTENSION 失败时 except 的
        # rollback 会把同一事务里 20+ 条 CREATE INDEX 一并回滚，SQLite 等
        # 回退环境最终 0 个索引（全部热路径退化全表扫描）。
        db.session.commit()
        try:
            db.session.execute(text('CREATE EXTENSION IF NOT EXISTS pg_trgm;'))
            # 仅学生姓名/学号/班级三列有 contains() 查询命中；question 内容、
            # homework 标题、resource 标题无模糊搜索需求，不再建 GIN
            # （此前建了也只是写放大，无查询命中）
            db.session.execute(text('CREATE INDEX IF NOT EXISTS idx_student_name_gin ON student USING gin (name gin_trgm_ops);'))
            db.session.execute(text('CREATE INDEX IF NOT EXISTS idx_student_number_gin ON student USING gin (student_number gin_trgm_ops);'))
            db.session.execute(text('CREATE INDEX IF NOT EXISTS idx_student_class_gin ON student USING gin (student_class gin_trgm_ops);'))
        except Exception:
            db.session.rollback()
            current_app.logger.warning(
                'pg_trgm 模糊搜索索引创建失败（已跳过，顺序扫描兜底）', exc_info=True)
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
