"""
ITstudy 智慧教学平台 V6.0.0
版权所有 (C) 2025-2026 YINJUN
仅供个人使用，不得商用
"""
from app import create_app

app = create_app()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
