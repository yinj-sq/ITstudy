# -*- coding: utf-8 -*-
"""学习活动提交 → 教师查看 → 评价全链路回归（2026-10-23）。

覆盖：学生上传文件/纯文本提交、教师作品云盘与活动详情、教师班级边界、
管理员全量视图、评价回显、重新提交后的待评价状态，以及教师首页统计
不能泄露其他班级的作品数量。
"""
import io
import uuid

import pytest

from app import create_app
from app.extensions import db
from app.models import (Class, LearningActivity, Resource, Student,
                        StudentWork, Teacher, WorkEvaluation)
from app.utils import delete_file_from_disk

CSRF = 't'


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


def _suffix():
    return uuid.uuid4().hex[:8]


def test_activity_submit_teacher_view_and_evaluate_chain(app):
    sfx = _suffix()
    cls_a_name = f'__act_a_{sfx}'
    cls_c_name = f'__act_c_{sfx}'
    res_title = f'__act_res_{sfx}'
    act_title = f'__act_act_{sfx}'
    t_name = f'__act_t_{sfx}'
    t2_name = f'__act_t2_{sfx}'
    s_name = f'__act_s_{sfx}'
    s2_name = f'__act_s2_{sfx}'
    ids = {}
    work_paths = []
    try:
        with app.app_context():
            cls_a = Class(name=cls_a_name)
            cls_c = Class(name=cls_c_name)
            teacher = Teacher(username=t_name, display_name='活动教师甲')
            teacher.set_password('pass123456')
            teacher.classes.append(cls_a)
            # 与本资源无关的教师，用于验证资源/班级边界
            teacher2 = Teacher(username=t2_name, display_name='活动教师乙')
            teacher2.set_password('pass123456')
            stu_a = Student(name='活动学生甲', student_number=s_name,
                            student_class=cls_a_name, has_changed_password=True)
            stu_a.set_password('pass123456')
            stu_c = Student(name='活动学生丙', student_number=s2_name,
                            student_class=cls_c_name, has_changed_password=True)
            stu_c.set_password('pass123456')
            db.session.add_all([cls_a, cls_c, teacher, teacher2, stu_a, stu_c])
            db.session.flush()
            stu_a.class_id, stu_c.class_id = cls_a.id, cls_c.id
            res = Resource(title=res_title, url='', show_in_student=True,
                           show_in_classroom=True, is_public=True,
                           creator_type='teacher',
                           creator_teacher_id=teacher.id,
                           creator_name=teacher.display_name)
            db.session.add(res)
            db.session.flush()
            act = LearningActivity(resource_id=res.id, title=act_title,
                                   description='请提交活动作品', require_upload=True,
                                   is_active=True)
            db.session.add(act)
            db.session.commit()
            ids = {
                't': teacher.id, 't2': teacher2.id, 'sa': stu_a.id,
                'sc': stu_c.id, 'res': res.id, 'act': act.id,
            }

        # 学生甲提交文件 + 文本；学生丙（非教师任课班）提交纯文本
        stu_a_client = _client(app, student_id=ids['sa'], student_name='活动学生甲',
                               has_changed_password=True)
        resp = _post(stu_a_client, f'/study/activity/{ids["act"]}', {
            'text_content': '学生甲的作品说明',
            'work_file': (io.BytesIO(b'activity work content'), 'answer.txt'),
        }, content_type='multipart/form-data')
        assert resp.status_code in (302, 303)
        stu_c_client = _client(app, student_id=ids['sc'], student_name='活动学生丙',
                               has_changed_password=True)
        resp = _post(stu_c_client, f'/study/activity/{ids["act"]}',
                     {'text_content': '学生丙的文本作品'})
        assert resp.status_code in (302, 303)
        with app.app_context():
            wa = StudentWork.query.filter_by(activity_id=ids['act'],
                                             student_id=ids['sa']).one()
            wc = StudentWork.query.filter_by(activity_id=ids['act'],
                                             student_id=ids['sc']).one()
            ids['wa'], ids['wc'] = wa.id, wc.id
            work_paths.append(wa.file_path)
            assert wa.status == 'submitted' and wa.original_filename == 'answer.txt'
            assert wc.status == 'submitted' and wc.text_content == '学生丙的文本作品'

        # 教师甲只看到本班作品（统计与详情同一班级边界）
        t_client = _client(app, is_teacher=True, teacher_id=ids['t'],
                           teacher_name='活动教师甲', teacher_mode='edit')
        works_html = t_client.get('/teacher/works').get_data(as_text=True)
        assert act_title in works_html
        assert '1 件作品' in works_html
        detail_html = t_client.get(
            f'/teacher/works/activity/{ids["act"]}').get_data(as_text=True)
        assert '活动学生甲' in detail_html and '学生甲的作品说明' in detail_html
        assert '活动学生丙' not in detail_html
        # 本班文件可由教师预览；其他班学生文件不可读
        assert t_client.get(f'/works/file/{ids["wa"]}/preview').status_code == 200
        assert t_client.get(f'/works/file/{ids["wc"]}/preview').status_code == 403
        # 无资源授权的教师不能查看活动详情或评价
        t2_client = _client(app, is_teacher=True, teacher_id=ids['t2'],
                            teacher_name='活动教师乙', teacher_mode='edit')
        assert t2_client.get(
            f'/teacher/works/activity/{ids["act"]}',
            follow_redirects=False).status_code == 302
        assert _post(t2_client, f'/teacher/works/evaluate/{ids["wa"]}', {
            'score': '1', 'grade': 'B', 'comment': '越权尝试',
        }).status_code in (302, 303)
        admin = _client(app, is_admin=True, admin_name='管理员')
        admin_html = admin.get(
            f'/admin/works/activity/{ids["act"]}').get_data(as_text=True)
        assert '活动学生甲' in admin_html and '活动学生丙' in admin_html

        # 教师甲评价甲的作品；学生端能看到评价
        resp = _post(t_client, f'/teacher/works/evaluate/{ids["wa"]}', {
            'score': '95', 'grade': 'A', 'comment': '完成得很好',
        })
        assert resp.status_code in (302, 303)
        with app.app_context():
            ev = WorkEvaluation.query.filter_by(work_id=ids['wa']).one()
            assert ev.score == 95 and ev.grade == 'A'
            assert db.session.get(StudentWork, ids['wa']).status == 'evaluated'
        page = stu_a_client.get(f'/study/activity/{ids["act"]}').get_data(as_text=True)
        assert '完成得很好' in page and '95' in page and 'A' in page

        # 重新提交：原评价保留，但列表/学生页明确提示待重新评价
        resp = _post(stu_a_client, f'/study/activity/{ids["act"]}',
                     {'text_content': '学生甲重新提交的说明'})
        assert resp.status_code in (302, 303)
        with app.app_context():
            wa = db.session.get(StudentWork, ids['wa'])
            assert wa.status == 'submitted'
            assert wa.evaluation is not None and wa.evaluation.score == 95
        teacher_page = t_client.get(
            f'/teacher/works/activity/{ids["act"]}').get_data(as_text=True)
        assert '待评价' in teacher_page and '上次' in teacher_page
        student_page = stu_a_client.get(
            f'/study/activity/{ids["act"]}').get_data(as_text=True)
        assert '上一次评价' in student_page and '等待教师重新评价' in student_page
        eval_page = t_client.get(
            f'/teacher/works/evaluate/{ids["wa"]}').get_data(as_text=True)
        assert '学生已重新提交作品' in eval_page
    finally:
        with app.app_context():
            if ids.get('act'):
                work_ids = [w.id for w in StudentWork.query.filter_by(
                    activity_id=ids['act']).all()]
                if work_ids:
                    WorkEvaluation.query.filter(
                        WorkEvaluation.work_id.in_(work_ids)).delete(
                            synchronize_session=False)
                    StudentWork.query.filter(
                        StudentWork.id.in_(work_ids)).delete(
                            synchronize_session=False)
                LearningActivity.query.filter_by(id=ids['act']).delete(
                    synchronize_session=False)
            if ids.get('res'):
                Resource.query.filter_by(id=ids['res']).delete(
                    synchronize_session=False)
            Student.query.filter(Student.student_number.in_(
                [s_name, s2_name])).delete(synchronize_session=False)
            # 先清关联表，再删教师/班级，避免批量删除绕过 secondary 级联
            db.session.execute(db.text(
                'DELETE FROM teacher_class WHERE teacher_id IN '
                '(SELECT id FROM teacher WHERE username IN (:a, :b))'
            ), {'a': t_name, 'b': t2_name})
            Teacher.query.filter(Teacher.username.in_(
                [t_name, t2_name])).delete(synchronize_session=False)
            Class.query.filter(Class.name.in_([cls_a_name, cls_c_name])).delete(
                synchronize_session=False)
            db.session.commit()
        for rel in work_paths:
            if rel:
                try:
                    delete_file_from_disk(rel)
                except Exception:
                    pass
