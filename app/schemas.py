from typing import Optional, List
from pydantic import BaseModel, Field, field_validator, ConfigDict


class StudentLogin(BaseModel):
    """学生登录表单校验 — 支持学号+密码或姓名+班级两种方式"""
    model_config = ConfigDict(populate_by_name=True)

    student_number: Optional[str] = Field(default=None, max_length=50)
    password: Optional[str] = Field(default=None, max_length=50)
    name: Optional[str] = Field(default=None, min_length=1, max_length=50)
    student_class: Optional[str] = Field(default=None, alias='class', max_length=50)

    @field_validator('name')
    @classmethod
    def name_strip(cls, v):
        return v.strip() if v else v

    @field_validator('student_class')
    @classmethod
    def class_strip(cls, v):
        return v.strip() if v else v

    @field_validator('student_number')
    @classmethod
    def number_strip(cls, v):
        return v.strip() if v else v


class AdminLogin(BaseModel):
    """管理员登录表单校验"""
    username: str = Field(..., min_length=1, max_length=80, description="管理员用户名")
    password: str = Field(..., min_length=1, max_length=128, description="管理员密码")

    @field_validator('username')
    @classmethod
    def username_not_empty(cls, v):
        if not v.strip():
            raise ValueError('用户名不能为空')
        return v.strip()


class ExamCreate(BaseModel):
    """创建试卷表单校验"""
    name: str = Field(..., min_length=1, max_length=100, description="试卷名称")

    @field_validator('name')
    @classmethod
    def name_not_empty(cls, v):
        if not v.strip():
            raise ValueError('试卷名称不能为空')
        return v.strip()


class ResourceCreate(BaseModel):
    """添加学习资源表单校验"""
    title: str = Field(..., min_length=1, max_length=200, description="资源标题")
    url: str = Field(..., min_length=1, max_length=500, description="资源链接")


class QuestionCreate(BaseModel):
    """创建题目表单校验"""
    exam_id: int = Field(..., gt=0, description="试卷ID")
    question_type: str = Field(...,
                               pattern=r'^(single|multiple|judge|fill|python_fill|comprehensive|link)$',
                               description="题目类型")
    content: str = Field(..., min_length=1, description="题目内容")
    options: Optional[str] = None
    answer: Optional[str] = None
    score: float = Field(default=1.0, gt=0, description="分值")
    python_answers: Optional[str] = None
    background: Optional[str] = None
    image_options: Optional[str] = None
    python_file_path: Optional[str] = None

    @field_validator('content')
    @classmethod
    def content_not_empty(cls, v):
        if not v.strip():
            raise ValueError('题目内容不能为空')
        return v.strip()


class QuestionUpdate(BaseModel):
    """编辑题目表单校验"""
    exam_id: int = Field(..., gt=0, description="试卷ID")
    content: str = Field(..., min_length=1, description="题目内容")
    options: Optional[str] = None
    answer: Optional[str] = None
    score: float = Field(default=1.0, gt=0, description="分值")
    python_answers: Optional[str] = None
    background: Optional[str] = None
    image_options: Optional[str] = None

    @field_validator('content')
    @classmethod
    def content_not_empty(cls, v):
        if not v.strip():
            raise ValueError('题目内容不能为空')
        return v.strip()


class SubQuestionCreate(BaseModel):
    """创建/添加小题表单校验"""
    sub_type: str = Field(..., min_length=1, description="小题类型")
    sub_content: str = Field(..., min_length=1, description="小题内容")
    sub_answer: str = Field(..., min_length=1, description="小题答案")
    sub_options: Optional[str] = ''
    sub_image_options: Optional[str] = ''
    sub_score: float = Field(default=1.0, gt=0, description="小题分值")


class ExcelImportCheck(BaseModel):
    """Excel导入校验"""
    exam_id: int = Field(..., gt=0, description="试卷ID")


class ExternalLinkCreate(BaseModel):
    """外链资源表单校验"""
    exam_id: int = Field(..., gt=0, description="试卷ID")
    external_link: str = Field(..., min_length=1, description="外链URL")


class PythonFileUploadCheck(BaseModel):
    """Python文件上传校验"""
    question_id: int = Field(..., gt=0, description="题目ID")
    python_file_path: Optional[str] = ''


class ResourceHomepage(BaseModel):
    """资源主页保存校验"""
    title: str = Field(..., min_length=1, description="资源标题")
    homepage: str = Field(..., min_length=1, description="主页文件路径")


class CompleteUploadCheck(BaseModel):
    """完成资源上传校验"""
    title: str = Field(..., min_length=1)
    directory: str = Field(..., min_length=1)
    homepage: str = Field(..., min_length=1)


def validate_form(schema_class, data_source):
    """统一的表单校验辅助函数

    Args:
        schema_class: Pydantic BaseModel 子类
        data_source: request.form (MultiDict) 或普通 dict

    Returns:
        成功时返回 (True, validated_data)
        失败时返回 (False, error_messages)
    """
    from pydantic import ValidationError
    try:
        validated = schema_class.model_validate(dict(data_source))
        return True, validated
    except ValidationError as e:
        errors = []
        for err in e.errors():
            msg = err.get('msg', '未知错误')
            errors.append(f"{msg}")
        return False, errors


# ──────────────────────────────────────────────
#  班级与学生管理相关 Schema
# ──────────────────────────────────────────────

class ClassCreate(BaseModel):
    """创建班级"""
    name: str = Field(..., min_length=1, max_length=50)
    description: Optional[str] = Field(default='', max_length=200)

    @field_validator('name')
    @classmethod
    def name_not_empty(cls, v):
        if not v.strip():
            raise ValueError('班级名称不能为空')
        return v.strip()


class ClassUpdate(BaseModel):
    """编辑班级"""
    name: str = Field(..., min_length=1, max_length=50)
    description: Optional[str] = Field(default='', max_length=200)

    @field_validator('name')
    @classmethod
    def name_not_empty(cls, v):
        if not v.strip():
            raise ValueError('班级名称不能为空')
        return v.strip()


class StudentCreate(BaseModel):
    """管理员创建/导入单个学生"""
    name: str = Field(..., min_length=1, max_length=50)
    student_number: Optional[str] = Field(default='', max_length=50)
    student_class: Optional[str] = Field(default='', max_length=50)
    class_id: Optional[int] = Field(default=None)
    password: Optional[str] = Field(default=None, max_length=50)

    @field_validator('name')
    @classmethod
    def name_not_empty(cls, v):
        if not v.strip():
            raise ValueError('学生姓名不能为空')
        return v.strip()

    @field_validator('student_number', 'student_class', mode='before')
    @classmethod
    def strip_text(cls, v):
        # 登录时学号会 strip：入库不 strip 的话 "2024001 " 永远登录不上
        return v.strip() if isinstance(v, str) else v

    @field_validator('class_id', mode='before')
    @classmethod
    def class_id_parse(cls, v):
        if v is None or v == '' or v == 'None':
            return None
        return int(v)


class StudentUpdate(BaseModel):
    """管理员编辑学生信息"""
    name: str = Field(..., min_length=1, max_length=50)
    student_number: Optional[str] = Field(default='', max_length=50)
    student_class: Optional[str] = Field(default='', max_length=50)
    class_id: Optional[int] = Field(default=None)
    group_id: Optional[int] = Field(default=None)
    is_activated: bool = True

    @field_validator('name')
    @classmethod
    def name_not_empty(cls, v):
        if not v.strip():
            raise ValueError('学生姓名不能为空')
        return v.strip()

    @field_validator('student_number', 'student_class', mode='before')
    @classmethod
    def strip_text(cls, v):
        return v.strip() if isinstance(v, str) else v

    @field_validator('class_id', 'group_id', mode='before')
    @classmethod
    def optional_int_parse(cls, v):
        if v is None or v == '' or v == 'None':
            return None
        return int(v)


class StudentPasswordReset(BaseModel):
    """重置单个学生密码"""
    new_password: str = Field(..., min_length=6, max_length=50)

    @field_validator('new_password')
    @classmethod
    def password_not_empty(cls, v):
        if not v.strip():
            raise ValueError('密码不能为空')
        return v.strip()


class StudentBatchPasswordReset(BaseModel):
    """批量重置密码"""
    student_ids: List[int] = Field(..., min_length=1)
    new_password: str = Field(..., min_length=6, max_length=50)


class StudentChangePassword(BaseModel):
    """学生自行修改密码"""
    old_password: str = Field(..., min_length=1, max_length=50)
    new_password: str = Field(..., min_length=6, max_length=50)

    @field_validator('new_password')
    @classmethod
    def password_not_empty(cls, v):
        if not v.strip():
            raise ValueError('新密码不能为空')
        return v.strip()


class GroupCreate(BaseModel):
    """创建学习小组"""
    name: str = Field(..., min_length=1, max_length=10)
    class_id: int = Field(..., gt=0)
    leader_id: Optional[int] = None

    @field_validator('leader_id', mode='before')
    @classmethod
    def leader_id_parse(cls, v):
        if v is None or v == '' or v == 'None':
            return None
        return int(v)


class GroupUpdate(BaseModel):
    """更新学习小组"""
    name: Optional[str] = Field(default=None, max_length=10)
    leader_id: Optional[int] = None

    @field_validator('leader_id', mode='before')
    @classmethod
    def leader_id_parse(cls, v):
        if v is None or v == '' or v == 'None':
            return None
        return int(v)


class StudentImportRow(BaseModel):
    """Excel/文本导入的单行数据"""
    name: str = Field(..., min_length=1, max_length=50)
    student_number: Optional[str] = Field(default='', max_length=50)
    student_class: Optional[str] = Field(default='', max_length=50)
