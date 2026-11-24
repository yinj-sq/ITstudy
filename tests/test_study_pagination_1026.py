# -*- coding: utf-8 -*-
"""学生资源页服务端分页/搜索/学科筛选回归（2026-10-26）。"""
import uuid

import pytest

from app import create_app
from app.extensions import cache, db
from app.models import Resource, Subject

CSRF = 'study-page-csrf'


@pytest.fixture(scope='module')
def app():
    return create_app()


def test_study_server_side_pagination_search_and_subject(app):
    sfx = uuid.uuid4().hex[:8]
    subj_name = f'__page_sub_{sfx}'
    titles = [f'__page_res_{sfx}_{i:02d}' for i in range(25)]
    sid = None
    try:
        cache.delete('study:resources:student')
        cache.delete('study:resources:scope:version')
        with app.app_context():
            subj = Subject(name=subj_name, sort_order=970)
            db.session.add(subj)
            db.session.flush()
            sid = subj.id
            db.session.add_all([
                Resource(title=t, url=f'https://example.com/{i}',
                         subject_id=sid, show_in_student=True,
                         show_in_classroom=True, quiz_mode='none')
                for i, t in enumerate(titles)
            ])
            db.session.commit()
        client = app.test_client()
        with client.session_transaction() as s:
            s['csrf_token'] = CSRF

        url = f'/study?subject={sid}'
        page1 = client.get(url).get_data(as_text=True)
        assert '共 25 个资源' in page1
        assert titles[0] in page1 and titles[11] in page1
        assert titles[12] not in page1
        assert '第 1 / 3 页' in page1

        page2 = client.get(url + '&page=2').get_data(as_text=True)
        assert titles[12] in page2 and titles[23] in page2
        assert titles[0] not in page2
        assert '第 2 / 3 页' in page2

        page3 = client.get(url + '&page=3').get_data(as_text=True)
        assert titles[24] in page3
        assert titles[0] not in page3
        assert '第 3 / 3 页' in page3

        searched = client.get(
            f'/study?subject={sid}&q={titles[24]}').get_data(as_text=True)
        assert titles[24] in searched
        assert titles[0] not in searched
        assert '共 1 个资源' in searched

        # 非法页码回退到最后一页，不 500
        bad = client.get(url + '&page=abc')
        assert bad.status_code == 200
        assert titles[0] in bad.get_data(as_text=True)
    finally:
        with app.app_context():
            if sid is not None:
                Resource.query.filter(Resource.title.like(f'__page_res_{sfx}%')).delete(
                    synchronize_session=False)
                Subject.query.filter_by(id=sid).delete(synchronize_session=False)
                db.session.commit()
            cache.delete('study:resources:student')
            cache.delete('study:resources:scope:version')
