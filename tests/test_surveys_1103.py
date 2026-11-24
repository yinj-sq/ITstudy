# -*- coding: utf-8 -*-
"""调查问卷模块回归（2026-11-03）。

覆盖：
- 教师编辑模式在自有资源（含未开放课堂）创建/编辑/发布/删除问卷；
  共享只读教师不可管理；管理员可管理；
- 题型解析（基础六题型 + 矩阵两题型）与非法输入拦截；
- 学生填写：草稿不可见、必答校验（含矩阵行）、每人一份、关闭/时间窗控制；
- 结果页聚合数据与匿名、CSV 导出、非管理者 403；
- 资源页/资源库/管理页入口与课堂章节树同步。
"""
import json
import uuid

import pytest

from app import create_app
from app.extensions import db
from app.models import (Class, ClassroomSession, Resource, Student,
                        Survey, SurveyAnswer, SurveyQuestion, Teacher,
                        TeachingSession, resource_share)

CSRF = 'survey-module-csrf'


@pytest.fixture(scope='module')
def app():
    return create_app()


def _client(app, **sess):
    client = app.test_client()
    with client.session_transaction() as s:
        s.update(sess)
        s['csrf_token'] = CSRF
    return client


def _post(client, path, data=None, **kwargs):
    data = dict(data or {})
    data.setdefault('csrf_token', CSRF)
    return client.post(path, data=data, headers={'X-CSRFToken': CSRF}, **kwargs)


def _q_form(questions):
    """题目数组 → 编辑器表单字段（与前端命名一致）。"""
    data = {}
    for i, q in enumerate(questions):
        data.setdefault('q_type', []).append(q['type'])
        data.setdefault('q_title', []).append(q['title'])
        data.setdefault('q_options', []).append(q.get('options', ''))
        data.setdefault('q_rows', []).append(q.get('rows', ''))
        if q.get('required'):
            data.setdefault('q_required', []).append(q['type'])
    return data


def _setup_owner_resource(app, sfx, show_in_classroom=False):
    with app.app_context():
        cls = Class(name=f'__sv_cls_{sfx}')
        owner = Teacher(username=f'__sv_own_{sfx}', display_name='问卷教师')
        owner.set_password('pass123456')
        other = Teacher(username=f'__sv_oth_{sfx}', display_name='共享教师')
        other.set_password('pass123456')
        stu = Student(name='问卷学生', student_number=f'__sv_s_{sfx}',
                      student_class=cls.name, has_changed_password=True)
        stu.set_password('pass123456')
        stu2 = Student(name='问卷学生2', student_number=f'__sv_s2_{sfx}',
                       student_class=cls.name, has_changed_password=True)
        stu2.set_password('pass123456')
        db.session.add_all([cls, owner, other, stu, stu2])
        db.session.flush()
        stu.class_id = cls.id
        stu2.class_id = cls.id
        res = Resource(title=f'__sv_res_{sfx}', url='',
                       show_in_student=True,
                       show_in_classroom=show_in_classroom,
                       creator_type='teacher',
                       creator_teacher_id=owner.id,
                       creator_name=owner.display_name)
        db.session.add(res)
        db.session.flush()
        db.session.add(ClassroomSession(class_id=cls.id, is_active=True))
        # 学生资源列表跟随授课教师：owner 正在该班上课
        db.session.add(TeachingSession(
            resource_id=res.id, teacher_id=owner.id,
            teacher_name=owner.display_name, class_id=cls.id,
            status='active'))
        db.session.execute(resource_share.insert().values(
            resource_id=res.id, teacher_id=other.id))
        db.session.commit()
        from app.blueprints.auth import invalidate_active_class_cache
        invalidate_active_class_cache()
        return {'cls': cls.id, 'owner': owner.id, 'other': other.id,
                'stu': stu.id, 'stu2': stu2.id, 'res': res.id}


def _cleanup(app, ids):
    with app.app_context():
        if ids.get('res'):
            TeachingSession.query.filter_by(
                resource_id=ids['res']).delete(synchronize_session=False)
            # bulk delete 不走 ORM 级联，先清问卷三级表再删资源
            sids = [row[0] for row in db.session.query(Survey.id).filter(
                Survey.resource_id == ids['res']).all()]
            if sids:
                SurveyAnswer.query.filter(
                    SurveyAnswer.survey_id.in_(sids)).delete(
                        synchronize_session=False)
                SurveyQuestion.query.filter(
                    SurveyQuestion.survey_id.in_(sids)).delete(
                        synchronize_session=False)
                Survey.query.filter(Survey.id.in_(sids)).delete(
                    synchronize_session=False)
            db.session.execute(resource_share.delete().where(
                resource_share.c.resource_id == ids['res']))
            Resource.query.filter_by(id=ids['res']).delete(
                synchronize_session=False)
        for key in ('owner', 'other'):
            if ids.get(key):
                Teacher.query.filter_by(id=ids[key]).delete(
                    synchronize_session=False)
        if ids.get('stu'):
            Student.query.filter(Student.id.in_(
                [ids['stu'], ids.get('stu2')])).delete(
                    synchronize_session=False)
        if ids.get('cls'):
            ClassroomSession.query.filter_by(
                class_id=ids['cls']).delete(synchronize_session=False)
            Class.query.filter_by(id=ids['cls']).delete(
                synchronize_session=False)
        db.session.commit()
        from app.blueprints.auth import invalidate_active_class_cache
        invalidate_active_class_cache()


def test_survey_lifecycle_teacher_and_admin(app):
    sfx = uuid.uuid4().hex[:8]
    ids = _setup_owner_resource(app, sfx, show_in_classroom=False)
    try:
        owner = _client(app, is_teacher=True, teacher_id=ids['owner'],
                        teacher_name='问卷教师', teacher_mode='edit')
        # 资源库与问卷列表入口（未开放课堂仍可编排问卷）
        lib = owner.get('/teacher/resource-library').get_data(as_text=True)
        assert f'/teacher/resources/{ids["res"]}/surveys' in lib
        list_page = owner.get(f'/teacher/resources/{ids["res"]}/surveys')
        assert list_page.status_code == 200
        assert '新增问卷' in list_page.get_data(as_text=True)

        # 创建：基础六题型 + 矩阵两题型
        form = _q_form([
            {'type': 'radio', 'title': '你喜欢本课吗？', 'required': True,
             'options': '喜欢\n一般\n不喜欢'},
            {'type': 'checkbox', 'title': '你用了哪些工具？',
             'options': '电脑\n平板\n手机'},
            {'type': 'select', 'title': '你的年级？',
             'options': '高一\n高二\n高三'},
            {'type': 'text', 'title': '你的姓名？', 'required': True},
            {'type': 'textarea', 'title': '对本课的建议'},
            {'type': 'score', 'title': '给本课打分'},
            {'type': 'matrix_radio', 'title': '对以下方面评价', 'required': True,
             'options': '满意\n一般\n不满意',
             'rows': '教师讲解\n实验操作\n课堂氛围'},
            {'type': 'matrix_score', 'title': '对以下方面打分（1-5）',
             'options': '1分\n2分\n3分\n4分\n5分',
             'rows': '内容难度\n节奏快慢'},
        ])
        form.update({'title': f'__sv_survey_{sfx}', 'description': '学习体验调查',
                     'is_anonymous': '1'})
        resp = _post(owner, f'/teacher/resources/{ids["res"]}/surveys/new', form)
        assert resp.status_code in (302, 303)
        with app.app_context():
            survey = Survey.query.filter_by(resource_id=ids['res']).one()
            ids['survey'] = survey.id
            assert survey.status == 'draft'
            assert survey.is_anonymous is True
            qs = sorted(survey.questions, key=lambda q: q.sort_order)
            assert [q.q_type for q in qs] == [
                'radio', 'checkbox', 'select', 'text', 'textarea', 'score',
                'matrix_radio', 'matrix_score']
            assert json.loads(qs[0].options) == ['喜欢', '一般', '不喜欢']
            assert qs[0].required is True
            assert json.loads(qs[6].row_titles) == ['教师讲解', '实验操作',
                                                    '课堂氛围']
            assert qs[6].options and qs[6].required

        # 草稿对学生不可见
        stu = _client(app, student_id=ids['stu'], student_name='问卷学生')
        assert f'__sv_survey_{sfx}' not in stu.get('/study').get_data(
            as_text=True)
        assert stu.get(f'/study/survey/{ids["survey"]}').status_code == 403

        # 共享教师（编辑模式）：资源未开放课堂时不可查看；管理操作 403
        shared = _client(app, is_teacher=True, teacher_id=ids['other'],
                         teacher_name='共享教师', teacher_mode='edit')
        resp = shared.get(f'/teacher/resources/{ids["res"]}/surveys')
        assert resp.status_code in (302, 303)
        assert _post(shared, f'/teacher/surveys/{ids["survey"]}/toggle'
                     ).status_code == 403
        # 只读教师受全局只读策略约束：管理页不可达（302 重定向）
        ro = _client(app, is_teacher=True, teacher_id=ids['other'],
                     teacher_name='共享教师', teacher_mode='readonly')
        resp = ro.get(f'/teacher/resources/{ids["res"]}/surveys')
        assert resp.status_code in (302, 303)

        # 发布 → 学生可见可填
        resp = _post(owner, f'/teacher/surveys/{ids["survey"]}/toggle')
        assert resp.status_code in (302, 303)
        study_text = stu.get('/study').get_data(as_text=True)
        assert f'__sv_survey_{sfx}' in study_text
        assert '未填' in study_text

        # 必答校验：缺必答单选与矩阵行 → 回到表单（302 + flash）
        fill = stu.get(f'/study/survey/{ids["survey"]}')
        assert fill.status_code == 200
        assert '喜欢本课吗' in fill.get_data(as_text=True)
        resp = _post(stu, f'/study/survey/{ids["survey"]}', {})
        assert resp.status_code in (302, 303)

        # 完整提交
        with app.app_context():
            survey = db.session.get(Survey, ids['survey'])
            qs = sorted(survey.questions, key=lambda q: q.sort_order)
            ids['qids'] = [q.id for q in qs]
        q = ids['qids']
        resp = _post(stu, f'/study/survey/{ids["survey"]}', {
            f'q{q[0]}': '喜欢',
            f'q{q[1]}': ['电脑', '平板'],
            f'q{q[2]}': '高二',
            f'q{q[3]}': '任意文本',
            f'q{q[4]}': '很好',
            f'q{q[5]}': '5',
            f'q{q[6]}__m0': '满意', f'q{q[6]}__m1': '一般', f'q{q[6]}__m2': '满意',
            f'q{q[7]}__m0': '4', f'q{q[7]}__m1': '5',
        })
        assert resp.status_code in (302, 303)
        with app.app_context():
            ans = SurveyAnswer.query.filter_by(
                survey_id=ids['survey'], student_id=ids['stu']).one()
            data = json.loads(ans.answers)
            assert data[str(q[0])] == '喜欢'
            assert data[str(q[1])] == ['电脑', '平板']
            assert data[str(q[6])] == {'教师讲解': '满意', '实验操作': '一般',
                                       '课堂氛围': '满意'}
            assert data[str(q[7])] == {'内容难度': '4', '节奏快慢': '5'}

        # 已填徽章与重复提交拦截
        assert '已填' in stu.get('/study').get_data(as_text=True)
        resp = _post(stu, f'/study/survey/{ids["survey"]}',
                     {f'q{q[0]}': '一般'})
        assert resp.status_code in (302, 303)
        with app.app_context():
            assert SurveyAnswer.query.filter_by(
                survey_id=ids['survey']).count() == 1

        # 结果页（匿名问卷不显示学生姓名）
        results = owner.get(f'/teacher/surveys/{ids["survey"]}/results')
        assert results.status_code == 200
        text = results.get_data(as_text=True)
        assert '1 份答卷' in text
        assert '喜欢' in text and '100.0%' in text
        assert '问卷学生' not in text  # 学生姓名不出现
        assert '平均分' in text  # score 聚合

        # CSV 导出
        csv_resp = owner.get(f'/teacher/surveys/{ids["survey"]}/results.csv')
        assert csv_resp.status_code == 200
        csv_text = csv_resp.get_data(as_text=True).lstrip('﻿')
        assert csv_text.startswith('提交时间,')
        # 矩阵题展开为逐行列；匿名卷无学生名列
        assert '你喜欢本课吗？' in csv_text
        assert '对以下方面评价｜教师讲解' in csv_text
        assert '电脑、平板' in csv_text
        assert '问卷学生' not in csv_text
        # 非管理者：CSV 403
        assert shared.get(f'/teacher/surveys/{ids["survey"]}/results.csv'
                          ).status_code == 403

        # 管理员可管理
        admin = _client(app, is_admin=True)
        assert admin.get(f'/admin/surveys/{ids["survey"]}/results'
                         ).status_code == 200

        # 关闭 → 未答学生 403，已答学生可回看
        _post(owner, f'/teacher/surveys/{ids["survey"]}/toggle')
        other_stu = _client(app, student_id=ids['stu2'], student_name='问卷学生2')
        assert other_stu.get(f'/study/survey/{ids["survey"]}'
                             ).status_code == 403
        assert stu.get(f'/study/survey/{ids["survey"]}').status_code == 200
        assert '我的答卷' in stu.get(
            f'/study/survey/{ids["survey"]}').get_data(as_text=True)

        # 编辑改名 → 显式课堂树同步 + 删除 → 树条目移除
        with app.app_context():
            res = db.session.get(Resource, ids['res'])
            res.lesson_tree = json.dumps([{
                'id': 's1', 'title': '课程内容', 'type': 'section',
                'children': [], 'items': [
                    {'id': 'i1', 'title': f'__sv_survey_{sfx}',
                     'kind': 'survey', 'src': '', 'survey_id': ids['survey'],
                     'visible': {'teacher': True, 'student': True}}]}],
                ensure_ascii=False)
            db.session.commit()
        resp = _post(owner, f'/teacher/surveys/{ids["survey"]}/edit', {
            'title': f'__sv_survey2_{sfx}', 'description': '',
            'q_type': ['radio'], 'q_title': ['改名后题目'],
            'q_options': ['甲\n乙'], 'q_rows': ['']})
        assert resp.status_code in (302, 303)
        with app.app_context():
            res = db.session.get(Resource, ids['res'])
            tree = json.loads(res.lesson_tree)
            assert tree[0]['items'][0]['title'] == f'__sv_survey2_{sfx}'
        resp = _post(owner, f'/teacher/surveys/{ids["survey"]}/delete')
        assert resp.status_code in (302, 303)
        with app.app_context():
            res = db.session.get(Resource, ids['res'])
            tree = json.loads(res.lesson_tree)
            # 条目移除后变空的章节同步清理（与活动同款逻辑）
            assert not tree
            assert Survey.query.filter_by(id=ids['survey']).first() is None
            assert SurveyAnswer.query.filter_by(
                survey_id=ids['survey']).count() == 0
    finally:
        _cleanup(app, ids)


def test_survey_editor_validation(app):
    sfx = uuid.uuid4().hex[:8]
    ids = _setup_owner_resource(app, sfx)
    try:
        owner = _client(app, is_teacher=True, teacher_id=ids['owner'],
                        teacher_name='问卷教师', teacher_mode='edit')
        # 单选题只有 1 个选项 → 拒绝
        form = _q_form([{'type': 'radio', 'title': '题目', 'options': '唯一'}])
        form['title'] = f'__sv_bad_{sfx}'
        resp = _post(owner, f'/teacher/resources/{ids["res"]}/surveys/new', form)
        assert resp.status_code in (302, 303)
        with app.app_context():
            assert Survey.query.filter_by(resource_id=ids['res']).count() == 0
        # 矩阵缺行 → 拒绝
        form = _q_form([{'type': 'matrix_radio', 'title': '矩阵',
                         'options': 'A\nB'}])
        form['title'] = f'__sv_bad2_{sfx}'
        _post(owner, f'/teacher/resources/{ids["res"]}/surveys/new', form)
        with app.app_context():
            assert Survey.query.filter_by(resource_id=ids['res']).count() == 0
        # 无题目 → 拒绝
        resp = _post(owner, f'/teacher/resources/{ids["res"]}/surveys/new',
                     {'title': f'__sv_bad3_{sfx}'})
        assert resp.status_code in (302, 303)
        with app.app_context():
            assert Survey.query.filter_by(resource_id=ids['res']).count() == 0
    finally:
        _cleanup(app, ids)


def test_survey_time_window(app):
    sfx = uuid.uuid4().hex[:8]
    ids = _setup_owner_resource(app, sfx)
    try:
        owner = _client(app, is_teacher=True, teacher_id=ids['owner'],
                        teacher_name='问卷教师', teacher_mode='edit')
        form = _q_form([{'type': 'text', 'title': '留言'}])
        form.update({'title': f'__sv_tw_{sfx}', 'status': 'published',
                     'end_time': '2020-01-01T00:00'})
        resp = _post(owner, f'/teacher/resources/{ids["res"]}/surveys/new', form)
        assert resp.status_code in (302, 303)
        with app.app_context():
            survey = Survey.query.filter_by(resource_id=ids['res']).one()
            ids['survey'] = survey.id
            assert survey.status == 'published'
            assert survey.end_time is not None
            ids['tw_qid'] = SurveyQuestion.query.filter_by(
                survey_id=survey.id).first().id
        stu = _client(app, student_id=ids['stu'], student_name='问卷学生')
        resp = _post(stu, f'/study/survey/{ids["survey"]}',
                     {f'q{ids["tw_qid"]}': 'hi'})
        assert resp.status_code in (302, 303)
        with app.app_context():
            assert SurveyAnswer.query.filter_by(
                survey_id=ids['survey']).count() == 0
    finally:
        _cleanup(app, ids)


def test_lesson_tree_default_includes_published_survey(app):
    sfx = uuid.uuid4().hex[:8]
    ids = _setup_owner_resource(app, sfx, show_in_classroom=True)
    try:
        owner = _client(app, is_teacher=True, teacher_id=ids['owner'],
                        teacher_name='问卷教师', teacher_mode='edit')
        form = _q_form([{'type': 'text', 'title': '反馈'}])
        form.update({'title': f'__sv_tree_{sfx}', 'status': 'published'})
        _post(owner, f'/teacher/resources/{ids["res"]}/surveys/new', form)
        with app.app_context():
            survey = Survey.query.filter_by(resource_id=ids['res']).one()
            ids['survey'] = survey.id
        stu = _client(app, student_id=ids['stu'], student_name='问卷学生')
        lesson = stu.get(f'/study/lesson/{ids["res"]}')
        assert lesson.status_code == 200
        text = lesson.get_data(as_text=True)
        assert f'__sv_tree_{sfx}' in text
        assert f'/study/survey/{ids["survey"]}' in text
    finally:
        _cleanup(app, ids)
