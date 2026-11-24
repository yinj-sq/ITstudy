; ============================================================
; ITstudy v6.1.0 安装脚本 (NSIS)
; 版权所有 (C) 2025-2026 YINJUN
; 仅供个人使用，不得商用
; ============================================================

!define PRODUCT_NAME "ITstudy"
!define PRODUCT_VERSION "6.1.0"
!define PRODUCT_PUBLISHER "YINJUN"
!define PRODUCT_DIR_REGKEY "Software\Microsoft\Windows\CurrentVersion\App Paths\ITstudy"
!define PRODUCT_UNINST_KEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\${PRODUCT_NAME}"
!define PRODUCT_SERVICE_NAME "ITstudy"

; ── 引入 ──
; TextFunc.nsh 提供 ${TrimNewLines}（pgPrerequisites 中剥离 "Python " 前缀用）；
; WordFunc.nsh 提供 ${VersionCompare}（版本号 ≥3.10 比对用）。
; 注意：两个宏均为"运行时调用宏"，只能在函数体内以参数形式调用
; （如 ${TrimNewLines} "$1" $PY_VER），文件级裸写 ${宏名} 是无效语法，
; 会导致编译失败 "Invalid command / macro requires N parameter(s)"。
!include "MUI2.nsh"
!include "nsDialogs.nsh"
!include "LogicLib.nsh"
!include "FileFunc.nsh"
!include "TextFunc.nsh"
!include "WordFunc.nsh"
!include "x64.nsh"

; ── 基本信息 ──
Name "${PRODUCT_NAME} ${PRODUCT_VERSION}"
OutFile "ITstudy-v${PRODUCT_VERSION}-Setup.exe"
InstallDir "$PROGRAMFILES64\${PRODUCT_NAME}"
InstallDirRegKey HKLM "${PRODUCT_DIR_REGKEY}" ""
ShowInstDetails show
ShowUnInstDetails show
RequestExecutionLevel admin

; ── 文件版本资源（Setup.exe 属性可见）──
VIProductVersion "6.1.0.0"
VIAddVersionKey /LANG=2052 "ProductName" "ITstudy"
VIAddVersionKey /LANG=2052 "FileDescription" "ITstudy 学科教学及测试平台安装程序"
VIAddVersionKey /LANG=2052 "FileVersion" "6.1.0"
VIAddVersionKey /LANG=2052 "ProductVersion" "6.1.0"
VIAddVersionKey /LANG=2052 "CompanyName" "YINJUN"
VIAddVersionKey /LANG=2052 "LegalCopyright" "Copyright (C) 2025-2026 YINJUN"

; ── 界面设置 ──
!define MUI_ABORTWARNING
!define MUI_ICON "assets\app.ico"
!define MUI_UNICON "assets\app.ico"
!define MUI_WELCOMEFINISHPAGE_BITMAP "assets\nsis-welcome.bmp"
!define MUI_HEADERIMAGE
!define MUI_HEADERIMAGE_BITMAP "assets\nsis-header.bmp"

; ── 页面 ──
!insertmacro MUI_PAGE_WELCOME
Page custom pgPrerequisites pgPrerequisitesLeave
!insertmacro MUI_PAGE_LICENSE "license-v6.0.rtf"
!insertmacro MUI_PAGE_DIRECTORY
Page custom pgPostgreSQL pgPostgreSQLLeave
!insertmacro MUI_PAGE_INSTFILES

!define MUI_FINISHPAGE_SHOWREADME ""
!define MUI_FINISHPAGE_SHOWREADME_TEXT "打开浏览器访问 ITstudy"
!define MUI_FINISHPAGE_SHOWREADME_FUNCTION OpenBrowser
!define MUI_FINISHPAGE_LINK "访问管理后台: http://localhost:5000/admin/login"
!define MUI_FINISHPAGE_LINK_LOCATION "http://localhost:5000/admin/login"
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES

!insertmacro MUI_LANGUAGE "SimpChinese"

; ── PostgreSQL 配置变量 ──
Var PG_HOST
Var PG_PORT
Var PG_NAME
Var PG_USER
Var PG_PASS
Var PG_HOST_TXT
Var PG_PORT_TXT
Var PG_NAME_TXT
Var PG_USER_TXT
Var PG_PASS_TXT

; ── 环境检测变量 ──
Var PY_FOUND
Var PG_FOUND
Var PY_VER
Var PY_VER_OK  ; 0 or 1, result of ${VersionCompare} (≥3.10 在线 / ==3.11.x 离线 wheels)
Var WHEELS_MODE  ; 0 or 1, $EXEDIR\wheels 存在时为 1（离线依赖模式，门槛 3.11.x）
Var CHK_PY_LBL
Var CHK_PG_LBL
Var CHK_WARN_LBL

; ============================================================
; 初始化：数据库默认值 + 命令行覆盖（供静默安装 /S 使用）
; ============================================================
; 默认值此前写在配置页函数 pgPostgreSQL 里，而静默安装（/S）跳过所有自定义
; 页面 → 页面函数不执行 → $PG_* 全为空 → postgresql.txt 被写成 `host=` 空值。
; config.py 的取值是 `环境变量 or 文件值 or 内置默认`，空串是假值 ⇒ 静默回落到
; **内置默认库 itstudy**；若本机 itstudy 恰好是生产库，无人值守安装会把新装的
; 服务悄悄接到生产数据上（本机实测复现：/S 安装后 postgresql.txt 五行全空）。
; 默认值移到 .onInit 后，任何安装方式都有一组明确的值，且可用命令行按需指定。
Function .onInit
    ; ── 强制子进程用 UTF-8 ──
    ; pip 读取 requirements.txt 时按 BOM → 前两行 PEP263 声明 → **locale 默认编码**
    ; 依次尝试解码；中文 Windows 的 locale 是 GBK，而该文件带 UTF-8 中文注释，
    ; 于是在「依赖安装」一步抛 UnicodeDecodeError、pip 退出码 2，安装必定中止
    ; （本机实测复现）。文件侧已加 `# -*- coding: utf-8 -*-` 声明兜底，这里再设
    ; PYTHONUTF8=1 让 pip 及一切 python 子进程按 UTF-8 解释文件与输出，双保险。
    System::Call 'kernel32::SetEnvironmentVariable(t "PYTHONUTF8", t "1")'

    StrCpy $PG_HOST "localhost"
    StrCpy $PG_PORT "5432"
    StrCpy $PG_NAME "itstudy"
    StrCpy $PG_USER "postgres"
    StrCpy $PG_PASS "@@"

    ; 命令行覆盖：/PGHOST= /PGPORT= /PGNAME= /PGUSER= /PGPASS=
    ; 例：ITstudy-v6.1.0-Setup.exe /S /PGNAME=itstudy_x /PGPASS=secret
    ; （值不能含空格；密码含空格/等号时请在页面上手工填写）
    ${GetOptions} $CMDLINE "/PGHOST=" $R0
    ${IfNot} ${Errors}
        StrCpy $PG_HOST $R0
    ${EndIf}
    ${GetOptions} $CMDLINE "/PGPORT=" $R0
    ${IfNot} ${Errors}
        StrCpy $PG_PORT $R0
    ${EndIf}
    ${GetOptions} $CMDLINE "/PGNAME=" $R0
    ${IfNot} ${Errors}
        StrCpy $PG_NAME $R0
    ${EndIf}
    ${GetOptions} $CMDLINE "/PGUSER=" $R0
    ${IfNot} ${Errors}
        StrCpy $PG_USER $R0
    ${EndIf}
    ${GetOptions} $CMDLINE "/PGPASS=" $R0
    ${IfNot} ${Errors}
        StrCpy $PG_PASS $R0
    ${EndIf}
FunctionEnd

; ============================================================
; 环境依赖检测页面（安装第一步，显著提醒）
; ============================================================
Function pgPrerequisites
    !insertmacro MUI_HEADER_TEXT "环境依赖检测" "安装前自动检测必需软件"

    nsDialogs::Create 1018
    Pop $0
    ${If} $0 == error
        Abort
    ${EndIf}

    ; ── 标题 ──
    ${NSD_CreateLabel} 0 0 100% 16u "ITstudy 需要以下软件支持，安装程序正在检测..."
    Pop $0

    ; ── 检测 Python ──
    StrCpy $PY_FOUND "0"
    StrCpy $PY_VER_OK "0"
    ClearErrors
    nsExec::ExecToStack 'cmd.exe /c python --version 2>&1'
    Pop $0  ; exit code
    Pop $1  ; stdout (redirected from stderr)
    ${If} $0 == 0
        ; 剥离 "Python " 前缀 (7 字符)，仅保留版本号如 "3.11.5"
        ${TrimNewLines} "$1" $PY_VER
        StrLen $R0 "Python "
        StrCpy $PY_VER $PY_VER "" $R0
        StrCpy $PY_FOUND "1"
        ; 版本门槛：离线 wheels 中的二进制包（psycopg2/pywin32/pillow/lxml/
        ; brotli/greenlet 等）全部为 cp311 专用——非 3.11 解释器 pip 找不到
        ; 兼容 wheel，--no-index 下必然报错中止。检测到安装包同目录 wheels\
        ; 时收紧为 3.11.x；在线安装（无 wheels）仍允许 3.10+。
        StrCpy $WHEELS_MODE "0"
        ${If} ${FileExists} "$EXEDIR\wheels\*.*"
            StrCpy $WHEELS_MODE "1"
        ${EndIf}
        ${If} $WHEELS_MODE == "1"
            ${VersionCompare} "$PY_VER" "3.11" $R1
            ${VersionCompare} "$PY_VER" "3.12" $R2
            ${If} $R1 >= 0
            ${AndIf} $R2 == -1
                StrCpy $PY_VER_OK "1"
            ${EndIf}
        ${Else}
            ; 检查 ≥ 3.10
            ${VersionCompare} "$PY_VER" "3.10" $R1
            ${If} $R1 >= 0
                StrCpy $PY_VER_OK "1"
            ${EndIf}
        ${EndIf}
    ${EndIf}

    ; ── 检测 PostgreSQL ──
    ; pg_isready 属 PostgreSQL **客户端工具**，很多机器只装了服务端、没装
    ; 客户端或没把 bin 加进 PATH：此时它直接「不是内部或外部命令」，脚本判为
    ; 未安装 → 页面误报「PostgreSQL 未运行或未安装」，用户被引去重装数据库
    ; （本机实测：PostgreSQL 18.4 服务正常、psql 不在 PATH，pg_isready 报
    ; command not found）。改用 python 的 socket 探测真实端口（python 本就是
    ; 本安装的前置依赖，探测失败再回退 pg_isready，两者都不可用才算缺失）。
    StrCpy $PG_FOUND "0"
    ${If} $PY_FOUND == "1"
        ClearErrors
        nsExec::ExecToStack "python -c $\"import socket;socket.create_connection(('localhost',5432),3)$\""
        Pop $0
        Pop $1
        ${If} $0 == 0
            StrCpy $PG_FOUND "1"
        ${EndIf}
    ${EndIf}
    ${If} $PG_FOUND == "0"
        ClearErrors
        nsExec::ExecToStack 'cmd.exe /c pg_isready -h localhost -p 5432 2>&1'
        Pop $0
        Pop $1
        ${If} $0 == 0
            StrCpy $PG_FOUND "1"
        ${EndIf}
    ${EndIf}

    ; ── Python 状态行 ──
    ${NSD_CreateLabel} 0 24u 20u 12u "Python:"
    ${If} $PY_VER_OK == "1"
        ${NSD_CreateLabel} 25u 24u 200u 12u "✔ 已安装 ($PY_VER)"
    ${ElseIf} $PY_FOUND == "1"
        ${If} $WHEELS_MODE == "1"
            ${NSD_CreateLabel} 25u 24u 200u 12u "⚠ Python $PY_VER (离线安装需 3.11.x，请调整)"
        ${Else}
            ${NSD_CreateLabel} 25u 24u 200u 12u "⚠ Python $PY_VER (需要 3.10+，请升级)"
        ${EndIf}
    ${Else}
        ${NSD_CreateLabel} 25u 24u 200u 12u "✘ 未检测到 Python 3.10+"
    ${EndIf}
    Pop $CHK_PY_LBL

    ; ── PostgreSQL 状态行 ──
    ${NSD_CreateLabel} 0 42u 20u 12u "数据库:"
    ${If} $PG_FOUND == "1"
        ${NSD_CreateLabel} 25u 42u 200u 12u "✔ PostgreSQL 已就绪 (localhost:5432)"
    ${Else}
        ${NSD_CreateLabel} 25u 42u 200u 12u "✘ PostgreSQL 未运行或未安装"
    ${EndIf}
    Pop $CHK_PG_LBL

    ; ── 警告提示 ──
    ${If} $PY_VER_OK == "0"
    ${OrIf} $PG_FOUND == "0"
        ${NSD_CreateLabel} 0 68u 100% 60u ""
        Pop $CHK_WARN_LBL
        ${If} $PY_FOUND == "1"
            ; Python 存在但版本不满足门槛
            ${If} $WHEELS_MODE == "1"
                ${NSD_SetText} $CHK_WARN_LBL "⚠ 警告：Python 版本与本安装包不兼容！$\r$\n$\r$\n  检测到 Python $PY_VER。$\r$\n  本安装包内置离线依赖（wheels\），仅支持 Python 3.11.x。$\r$\n  请安装 Python 3.11.x（勾选 'Add Python to PATH'）后重试，$\r$\n  或改用不带 wheels 的在线安装包（Python 3.10+）。$\r$\n$\r$\n您可以继续安装，但依赖安装阶段将失败。"
            ${Else}
                ${NSD_SetText} $CHK_WARN_LBL "⚠ 警告：Python 版本过低！$\r$\n$\r$\n  检测到 Python $PY_VER（需 3.10+）。$\r$\n  请升级到 Python 3.10 或更高版本。$\r$\n$\r$\n  • Python 3.10+ 下载：https://www.python.org/downloads/$\r$\n    （安装时请勾选 'Add Python to PATH'）$\r$\n$\r$\n您可以继续安装，但服务可能无法启动，请升级后重试。"
            ${EndIf}
        ${ElseIf} $PG_FOUND == "0"
            ; Python 和 PostgreSQL 均缺失
            ${NSD_SetText} $CHK_WARN_LBL "⚠ 警告：缺少必需环境！$\r$\n$\r$\n  • Python 3.10+ 下载：https://www.python.org/downloads/$\r$\n    （安装时请勾选 'Add Python to PATH'）$\r$\n$\r$\n  • PostgreSQL 12+ 下载：https://www.postgresql.org/download/windows/$\r$\n$\r$\n您可以继续安装，但服务将无法启动，请安装后重试。"
        ${Else}
            ; 仅 PostgreSQL 缺失
            ${NSD_SetText} $CHK_WARN_LBL "⚠ 警告：缺少 PostgreSQL 数据库！$\r$\n$\r$\n  • PostgreSQL 12+ 下载：https://www.postgresql.org/download/windows/$\r$\n$\r$\n您可以继续安装，但服务将无法启动，请安装后重试。"
        ${EndIf}
        SendMessage $CHK_WARN_LBL ${WM_SETFONT} 0 0
    ${Else}
        ${NSD_CreateLabel} 0 68u 100% 16u "✔ 所有环境依赖已就绪，可以继续安装。"
        Pop $CHK_WARN_LBL
    ${EndIf}

    nsDialogs::Show
FunctionEnd

Function pgPrerequisitesLeave
    ${If} $PY_VER_OK == "0"
    ${OrIf} $PG_FOUND == "0"
        ${If} $PY_FOUND == "1"
            StrCpy $R2 "$PY_VER"
        ${Else}
            StrCpy $R2 "未找到"
        ${EndIf}
        ${If} $PG_FOUND == "1"
            StrCpy $R3 "已就绪"
        ${Else}
            StrCpy $R3 "未运行"
        ${EndIf}
        MessageBox MB_YESNO|MB_ICONEXCLAMATION \
            "检测到以下环境问题，缺少将导致 ITstudy 无法正常运行：$\r$\n$\r$\n  • Python 3.10+：$R2$\r$\n  • PostgreSQL 12+：$R3$\r$\n$\r$\n是否仍要继续安装？" \
            /SD IDYES IDYES continue
            Abort
        continue:
    ${EndIf}
FunctionEnd

; ============================================================
; PostgreSQL 配置页面
; ============================================================
Function pgPostgreSQL
    !insertmacro MUI_HEADER_TEXT "数据库配置" "配置 PostgreSQL 连接信息"
    
    nsDialogs::Create 1018
    Pop $0
    
    ${If} $0 == error
        Abort
    ${EndIf}
    
    ; 默认值由 .onInit 统一赋值（含 /PGHOST= 等命令行覆盖），此处不得重设：
    ; 在页面函数里再赋一次会把命令行传进来的取值悄悄冲掉，GUI 与静默两条
    ; 路径的初始值也会分叉。控件初值直接取 $PG_*，所见即 .onInit 的结果。

    ${NSD_CreateLabel} 0 0 100% 12u "请填写 PostgreSQL 数据库连接信息："
    
    ${NSD_CreateLabel} 0 20u 60u 12u "主机地址："
    ${NSD_CreateText} 65u 20u 100u 12u $PG_HOST
    Pop $PG_HOST_TXT
    
    ${NSD_CreateLabel} 0 40u 60u 12u "端口："
    ${NSD_CreateText} 65u 40u 60u 12u $PG_PORT
    Pop $PG_PORT_TXT
    
    ${NSD_CreateLabel} 0 60u 60u 12u "数据库名："
    ${NSD_CreateText} 65u 60u 100u 12u $PG_NAME
    Pop $PG_NAME_TXT
    
    ${NSD_CreateLabel} 0 80u 60u 12u "用户名："
    ${NSD_CreateText} 65u 80u 100u 12u $PG_USER
    Pop $PG_USER_TXT
    
    ${NSD_CreateLabel} 0 100u 60u 12u "密码："
    ${NSD_CreatePassword} 65u 100u 100u 12u $PG_PASS
    Pop $PG_PASS_TXT
    
    ${NSD_CreateLabel} 0 130u 100% 24u "提示：安装程序会自动检测并创建数据库。$\r$\n如果 PostgreSQL 未安装，请先安装 PostgreSQL 12+。"
    
    nsDialogs::Show
FunctionEnd

Function pgPostgreSQLLeave
    ${NSD_GetText} $PG_HOST_TXT $PG_HOST
    ${NSD_GetText} $PG_PORT_TXT $PG_PORT
    ${NSD_GetText} $PG_NAME_TXT $PG_NAME
    ${NSD_GetText} $PG_USER_TXT $PG_USER
    ${NSD_GetText} $PG_PASS_TXT $PG_PASS
FunctionEnd

; ============================================================
; 安装
; ============================================================
Section "MainSection" SEC01
    ; ── 覆盖安装：先停掉正在运行的服务 ──
    ; 服务在跑时 python.exe、依赖 dll、前端文件被进程占用，随后 File 覆盖会失败
    ; （安装中止在半途）。此前服务从未真正启动过（pywin32 宿主 exe 问题，见
    ; itstudy_service.py 的 _exe_name_ 注释），该冲突不显现；宿主修好后必须补。
    ; nsExec 不弹控制台窗口，输出进安装详情；服务不存在/未运行时返回非 0 ——
    ; 忽略即可，两种情况都不影响后续安装。
    nsExec::ExecToLog 'net stop ${PRODUCT_SERVICE_NAME}'

    SetOutPath "$INSTDIR"
    SetOverwrite on
    
    ; ── 复制项目文件 ──
    ; 关键（NSIS 语义陷阱一）：`File /r "..\<dir>\*.*"` 通配形式只保留
    ; "通配符以下"的相对目录结构——若 OutPath 停在 $INSTDIR，app\templates\
    ; static\ 等整棵树会被展平到安装根目录（config.py 落在根、blueprints\
    ; 落在根下），服务启动即 ModuleNotFoundError。每个目录树复制前必须
    ; 先 SetOutPath 到对应安装子目录（已用 sandbox 编译+安装实测验证）
    ;
    ; 关键（NSIS 语义陷阱二）：`/r` 用在**单个文件名**上不是"就复制这一个
    ; 文件"，而是把该名字当查找掩码，从上层目录起**递归遍历整棵源码树**搜
    ; 同名文件、并按相对路径还原目录。本机 makensis /V4 打包清单实证：
    ; `File /r "..\app.py"` 把 venv\Lib\site-packages\flask\sansio\app.py、
    ; pythonwin\pywin\framework\app.py 一并打入；`File /r "..\LICENSE"` 把
    ; venv 里每个 *-dist-info\licenses\LICENSE 全打进包（共 110 条 venv 引用）。
    ; 解包时这些文件落在 $INSTDIR\venv\Lib\site-packages\ 下，**先于**后面的
    ; `python -m venv` 建好目录树，而 venv 不会清理陌生目录 ⇒ 装出的
    ; site-packages 混着开发机残留：裸 numpy\ 目录（只含 ma\LICENSE 无 .py）
    ; 让 `import numpy` 命中空壳包，openpyxl 的 `try: import numpy` 随之
    ; AttributeError: module 'numpy' has no attribute 'short'，Excel 导入导出全挂
    ; （本机 /D= 全新目录装机复现：site-packages 149 条 vs 干净装机 7 条）。
    ; ⇒ 单文件一律**不带 /r**；/r 只用于目录或通配符。
    SetOutPath "$INSTDIR"
    File "..\app.py"
    File "..\itstudy_service.py"
    File "..\run_zh.bat"
    File "..\requirements.txt"
    File "..\constraints.txt"
    ; 注意：不打包 admin_account.txt——其为运行期生成的敏感凭据文件
    ; （含 scrypt 密码哈希，随安装包分发会共享固定凭据且污染干净构建；
    ; 首次启动自动生成随机密码，见《安装使用说明》第四节「第一次登录」
    ; （服务方式无控制台时，密码同时写入受 ACL 保护的
    ;  admin_account.initial.txt，首次登录成功后自动删除）
    File "..\LICENSE"
    File /oname=LICENSE-v6.0.txt "license-v6.0.txt"
    File "..\cdn_config.json"
    ; 项目入口说明（快速入口表/核心能力/开发与回归命令），便于安装后查阅
    File "..\README.md"
    SetOutPath "$INSTDIR\app"
    ; 运行期日志目录（app.log 等）属开发机残留，装机由 $INSTDIR\logs 统一承载
    File /r /x "__pycache__" /x "logs" "..\app\*.*"
    SetOutPath "$INSTDIR\templates"
    File /r "..\templates\*.*"
    SetOutPath "$INSTDIR\static"
    ; 排除运行期上传/提交数据（应用启动时会自动创建这些空目录），避免打包开发机测试数据
    File /r /x "uploads" /x "submissions" /x "homework" /x "chunks" /x "question_img" "..\static\*.*"
    SetOutPath "$INSTDIR\frontend"
    File /r "..\frontend\*.*"
    SetOutPath "$INSTDIR\migrations"
    File /r /x "__pycache__" "..\migrations\*.*"
    SetOutPath "$INSTDIR\docs"
    ; 审查报告不随包分发（漏洞细节不落客户机）：按文件名单模式排除，
    ; 覆盖未来新增的任意《*审查*.md》《*复审*.md》，不再依赖逐名枚举
    ; 安全审查/复审/专家评审报告不下发客户机（漏洞细节与内部风险）
    File /r /x "*审查*.md" /x "*复审*.md" /x "*评审*.md" /x "*评估*.md" "..\docs\*.*"
    SetOutPath "$INSTDIR\tools"
    ; 运维工具（文档指示安装后使用：密码重置/日志归档/静态预压缩等）。
    ; e2e_*/review_* 是开发期回归与审查脚本（依赖 Playwright、连隔离测试库），
    ; ketcher-app 是 Ketcher 构建源码（含 node_modules），对装机无用，不随包分发
    File /r /x "__pycache__" /x "e2e_*.py" /x "review_*.py" /x "ketcher-app" "..\tools\*.*"
    SetOutPath "$INSTDIR"
    
    ; ── 创建数据目录 ──
    CreateDirectory "$INSTDIR\data"
    CreateDirectory "$INSTDIR\data\cache"
    CreateDirectory "$INSTDIR\logs"
    CreateDirectory "$INSTDIR\instance"
    CreateDirectory "$INSTDIR\venv"
    ; 真实上传数据目录：应用的上传根是 static\uploads（资源/网盘/Python 文件），
    ; 作业附件、学生提交等子目录在首次使用时自动创建。这里显式预建，便于运维
    ; 备份与卸载时识别数据位置；不再创建旧版根目录 uploads（非真实数据目录）。
    CreateDirectory "$INSTDIR\static\uploads"
    CreateDirectory "$INSTDIR\static\homework"
    CreateDirectory "$INSTDIR\static\submissions"
    CreateDirectory "$INSTDIR\static\chunks"
    CreateDirectory "$INSTDIR\static\question_img"
    
    ; ── 校验数据库配置（防「静默回落到内置默认库」）──
    ; postgresql.txt 里的空值在 config.py 中不是「缺省」而是**假值**：
    ; `环境变量 or 文件值 or 内置默认` 会直接落到内置默认库 itstudy。若本机
    ; itstudy 恰是生产库，装出来的服务会悄悄连到生产数据上（无人值守安装尤其
    ; 危险）。此处宁可中止安装，也不允许写出空值配置。
    ; 密码允许留空：PostgreSQL trust 认证本就无需密码，且空密码在 config.py
    ; 里同样回落到内置默认值 '@@'，不会造成接错库。
    ${If} $PG_HOST == ""
    ${OrIf} $PG_PORT == ""
    ${OrIf} $PG_NAME == ""
    ${OrIf} $PG_USER == ""
        MessageBox MB_ICONSTOP "数据库配置不完整，安装已中止。$\r$\n$\r$\n  主机：$PG_HOST$\r$\n  端口：$PG_PORT$\r$\n  数据库名：$PG_NAME$\r$\n  用户名：$PG_USER$\r$\n$\r$\n空值会被程序回落到内置默认库 itstudy，可能误接到其他数据库。$\r$\n静默安装请用 /PGHOST= /PGPORT= /PGNAME= /PGUSER= 显式指定。" /SD IDOK
        Abort "数据库配置不完整。"
    ${EndIf}
    ${If} $PG_PORT < 1
        MessageBox MB_ICONSTOP "端口不合法：「$PG_PORT」。$\r$\n端口应为 1-65535 的整数，请重新运行安装程序并填写正确端口。" /SD IDOK
        Abort "端口不合法。"
    ${EndIf}

    ; ── 写入数据库配置 ──
    ClearErrors
    FileOpen $0 "$INSTDIR\postgresql.txt" w
    FileWrite $0 "host=$PG_HOST$\r$\n"
    FileWrite $0 "port=$PG_PORT$\r$\n"
    FileWrite $0 "dbname=$PG_NAME$\r$\n"
    FileWrite $0 "user=$PG_USER$\r$\n"
    FileWrite $0 "password=$PG_PASS$\r$\n"
    FileClose $0
    
    ; ── 创建虚拟环境并安装依赖 ──
    DetailPrint "正在创建 Python 虚拟环境..."
    ExecWait '"$SYSDIR\cmd.exe" /c "python -m venv "$INSTDIR\venv""' $0
    ${If} $0 != "0"
        MessageBox MB_ICONSTOP "Python 虚拟环境创建失败 (exit: $0)。$\n请确认已安装 Python 3.10+ 并在 PATH 中，然后重新运行安装程序。" /SD IDOK
        Abort "安装已中止。"
    ${EndIf}

    DetailPrint "正在安装 Python 依赖..."
    ; 离线优先：安装包同目录存在 wheels\ 时完全离线安装（断网机房）；
    ; 否则回退在线（清华镜像）
    ${If} ${FileExists} "$EXEDIR\wheels\*.*"
        DetailPrint "检测到离线 wheel 包，离线安装依赖..."
        ExecWait '"$SYSDIR\cmd.exe" /c ""$INSTDIR\venv\Scripts\pip.exe" install --no-index --find-links "$EXEDIR\wheels" -c "$INSTDIR\constraints.txt" -r "$INSTDIR\requirements.txt""' $0
    ${Else}
        ExecWait '"$SYSDIR\cmd.exe" /c ""$INSTDIR\venv\Scripts\pip.exe" install -c "$INSTDIR\constraints.txt" -r "$INSTDIR\requirements.txt" -i https://pypi.tuna.tsinghua.edu.cn/simple"' $0
    ${EndIf}
    ${If} $0 != "0"
        ${If} $WHEELS_MODE == "1"
            MessageBox MB_ICONSTOP "Python 依赖安装失败 (exit: $0)。$\n离线安装要求 Python 3.11.x（wheels 为 cp311 专用），请核对后重试；$\n或移除安装包同目录的 wheels\ 改为在线安装（3.10+）。" /SD IDOK
        ${Else}
            MessageBox MB_ICONSTOP "Python 依赖安装失败 (exit: $0)。$\n请查看上方日志；离线环境请将 wheels 目录置于安装包同目录$\n（离线 wheels 仅支持 Python 3.11.x）。" /SD IDOK
        ${EndIf}
        Abort "安装已中止。"
    ${EndIf}

    DetailPrint "正在注册 Windows 服务..."
    ExecWait '"$SYSDIR\cmd.exe" /c ""$INSTDIR\venv\Scripts\python.exe" "$INSTDIR\itstudy_service.py" --startup auto install"' $0
    ${If} $0 != "0"
        MessageBox MB_ICONSTOP "Windows 服务注册失败 (exit: $0)。$\n请以管理员身份重新运行安装程序。" /SD IDOK
        Abort "安装已中止。"
    ${EndIf}

    DetailPrint "正在启动 ITstudy 服务..."
    ExecWait 'net start ${PRODUCT_SERVICE_NAME}' $0
    ${If} $0 != "0"
        MessageBox MB_ICONEXCLAMATION "服务启动失败 (exit: $0)。$\n程序文件已就绪，可稍后在 services.msc 启动 ${PRODUCT_SERVICE_NAME}，$\n或查看 $INSTDIR\logs\app.log 排查。" /SD IDOK
    ${EndIf}
    
    ; ── 创建快捷方式 ──
    CreateDirectory "$SMPROGRAMS\${PRODUCT_NAME}"
    ; URL 快捷方式必须显式指定图标：Windows 对 http(s) 目标默认只给空白/
    ; 浏览器通用图标（本机实测 IconLocation 为空 → 桌面快捷方式无图案）。
    CreateShortCut "$SMPROGRAMS\${PRODUCT_NAME}\ITstudy 学生端.lnk" "http://localhost:5000" "" "$INSTDIR\static\favicon.ico" 0
    CreateShortCut "$SMPROGRAMS\${PRODUCT_NAME}\ITstudy 管理端.lnk" "http://localhost:5000/admin/login" "" "$INSTDIR\static\favicon.ico" 0
    CreateShortCut "$SMPROGRAMS\${PRODUCT_NAME}\停止服务.lnk" "net" "stop ${PRODUCT_SERVICE_NAME}" "$INSTDIR\static\favicon.ico" 0
    CreateShortCut "$SMPROGRAMS\${PRODUCT_NAME}\启动服务.lnk" "net" "start ${PRODUCT_SERVICE_NAME}" "$INSTDIR\static\favicon.ico" 0
    CreateShortCut "$DESKTOP\ITstudy.lnk" "http://localhost:5000" "" "$INSTDIR\static\favicon.ico" 0
SectionEnd

Section -AdditionalIcons
    CreateShortCut "$SMPROGRAMS\${PRODUCT_NAME}\卸载.lnk" "$INSTDIR\uninst.exe" "" "$INSTDIR\static\favicon.ico" 0
SectionEnd

Section -Post
    WriteUninstaller "$INSTDIR\uninst.exe"
    WriteRegStr HKLM "${PRODUCT_DIR_REGKEY}" "" "$INSTDIR\app.py"
    WriteRegStr HKLM "${PRODUCT_DIR_REGKEY}" "Path" "$INSTDIR"
    WriteRegStr HKLM "${PRODUCT_UNINST_KEY}" "DisplayName" "$(^Name)"
    WriteRegStr HKLM "${PRODUCT_UNINST_KEY}" "UninstallString" "$INSTDIR\uninst.exe"
    WriteRegStr HKLM "${PRODUCT_UNINST_KEY}" "DisplayVersion" "${PRODUCT_VERSION}"
    WriteRegStr HKLM "${PRODUCT_UNINST_KEY}" "Publisher" "${PRODUCT_PUBLISHER}"
    WriteRegStr HKLM "${PRODUCT_UNINST_KEY}" "DisplayIcon" "$INSTDIR\static\favicon.ico"
    ${GetSize} "$INSTDIR" "/S=0K" $0 $1 $2
    IntFmt $0 "0x%08X" $0
    WriteRegDWORD HKLM "${PRODUCT_UNINST_KEY}" "EstimatedSize" "$0"
SectionEnd

; ============================================================
; 卸载
; ============================================================
Section Uninstall
    ; ── 停止并删除服务 ──
    DetailPrint "正在停止 ITstudy 服务..."
    ExecWait 'net stop ${PRODUCT_SERVICE_NAME}' $0
    DetailPrint "正在删除 Windows 服务..."
    ExecWait '"$SYSDIR\cmd.exe" /c ""$INSTDIR\venv\Scripts\python.exe" "$INSTDIR\itstudy_service.py" remove"' $0
    
    ; ── 删除文件 ──
    ; 数据保留选项：instance（密钥/配置）、data（缓存）、static（真实上传数据
    ; 位于 static\uploads/homework/submissions/question_img/chunks）——保留便于
    ; 重装恢复。旧版根目录 uploads 只是历史外链 .url 目录，不是项目数据目录：
    ; 删除数据分支整目录清理，保留分支仅在为空时顺手移除（含 .url 则保留）。
    ; backups（日志归档）两个分支都会清理：它只是 archive_logs.py 已导出日志的
    ; 副本，保留无价值且体积随运行持续增长（故下面 keep_data 里也删它，
    ; 弹窗文案必须如实写明，否则用户会以为"否"能保住备份）
    ; 命令行 /DELDATA=1 删除运行数据、/DELDATA=0 保留（供静默卸载
    ; `uninst.exe /S` 使用）；未指定才弹窗，且静默缺省「否」= 保留
    ; （/SD IDNO：无人值守卸载绝不擅自删数据）
    StrCpy $R9 ""
    ${GetOptions} $CMDLINE "/DELDATA=" $R9
    ${If} $R9 == "1"
        Goto del_data
    ${EndIf}
    ${If} $R9 == "0"
        Goto keep_data
    ${EndIf}
    MessageBox MB_YESNO|MB_ICONQUESTION "是否同时删除运行数据？$\n$\n「是」：删除 instance（密钥/配置）、data、backups、static（含 static\uploads 等全部上传数据）、旧版 uploads（如存在）$\n「否」：保留 instance、data、static（含 static\uploads 等上传数据）（推荐，重装后数据无损）$\n$\n注：backups（日志归档）两个选项都会清理" /SD IDNO IDYES del_data
    Goto keep_data
  del_data:
    RMDir /r "$INSTDIR\instance"
    RMDir /r "$INSTDIR\data"
    RMDir /r "$INSTDIR\backups"
    RMDir /r "$INSTDIR\static"
    ; 旧版安装可能残留根目录 uploads（历史外链 .url）；新版本不再创建它。
    ; 删除数据分支将其一并清理，否则下面 del_prog 的 RMDir "$INSTDIR"
    ; （仅在目录已空时生效）会因残留而静默失败，留下半截安装目录。
    RMDir /r "$INSTDIR\uploads"
    Goto del_prog
  keep_data:
    ; 保留数据：static 整树保留（含 static\uploads/homework/submissions/
    ; question_img 等真实上传数据；重装时程序资产被新版本覆盖，数据无损）；
    ; 旧版根目录 uploads 若为空则移除，若含历史 .url 外链文件则原样保留
    RMDir "$INSTDIR\uploads"
    RMDir /r "$INSTDIR\backups"
  del_prog:
    Delete "$INSTDIR\*.*"
    RMDir /r "$INSTDIR\app"
    RMDir /r "$INSTDIR\templates"
    RMDir /r "$INSTDIR\migrations"
    RMDir /r "$INSTDIR\frontend"
    RMDir /r "$INSTDIR\docs"
    RMDir /r "$INSTDIR\tools"
    RMDir /r "$INSTDIR\venv"
    RMDir /r "$INSTDIR\logs"
    RMDir "$INSTDIR"
    
    ; ── 删除快捷方式 ──
    Delete "$SMPROGRAMS\${PRODUCT_NAME}\*.*"
    RMDir "$SMPROGRAMS\${PRODUCT_NAME}"
    Delete "$DESKTOP\ITstudy.lnk"
    
    ; ── 清理注册表 ──
    DeleteRegKey HKLM "${PRODUCT_UNINST_KEY}"
    DeleteRegKey HKLM "${PRODUCT_DIR_REGKEY}"
    
    SetAutoClose true
SectionEnd

; ============================================================
; 安装完成后打开浏览器
; ============================================================
Function OpenBrowser
    ExecShell "open" "http://localhost:5000"
FunctionEnd
