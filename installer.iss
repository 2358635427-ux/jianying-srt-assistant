; ============================================================================
;  Inno Setup 安装脚本 — 剪映字幕助手 (Draft SRT Assistant)
; ============================================================================
;  使用方法 (在 Windows 上):
;     1. 先运行:  pyinstaller build_win.spec
;     2. 然后运行:  iscc installer.iss
;  输出:  Output/剪映字幕助手_Setup_{version}.exe
;
;  需要安装 Inno Setup (免费):  https://jrsoftware.org/isinfo.php
; ============================================================================

#define MyAppName       "剪映字幕助手"
#define MyAppNameEn     "Draft SRT Assistant"
#define MyAppVersion    "1.5.0"
#define MyAppPublisher  "小方"
#define MyAppURL        ""
#define MyAppExeName    "剪映字幕助手.exe"

[Setup]
; 注: AppId 必须唯一，请勿修改
AppId={{8E9C4F2A-7B6D-4A3E-9F1C-2D5E8A7B6C3D}}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} v{#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
; 允许用户自定义安装目录
DisableDirPage=no
; 默认开始菜单位置
DefaultGroupName={#MyAppName}
; 允许用户选择是否创建开始菜单快捷方式
DisableProgramGroupPage=no
; 安装程序图标 (若项目根目录有 icon.ico 则使用)
SetupIconFile=icon.ico
; 压缩方式
Compression=lzma2/ultra64
SolidCompression=yes
; Windows 7 及以上
MinVersion=6.1
; 安装/卸载都需要管理员权限（可选）
; PrivilegesRequired=admin
; 输出目录
OutputDir=Output
; 输出文件名
OutputBaseFilename=剪映字幕助手_Setup_v{#MyAppVersion}
; 支持的系统架构
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
; 桌面快捷方式
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "其他:"

[Files]
; 将 PyInstaller 打包产物全部复制到安装目录
Source: "dist\剪映字幕助手\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
; 开始菜单快捷方式
Name: "{group}\{#MyAppName}";       Filename: "{app}\{#MyAppExeName}"
Name: "{group}\卸载 {#MyAppName}";  Filename: "{uninstallexe}"
; 桌面快捷方式（可选）
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
; 安装完成后询问是否启动程序
Filename: "{app}\{#MyAppExeName}"; \
    Description: "启动 {#MyAppName}"; \
    Flags: nowait postinstall skipifsilent

[UninstallDelete]
; 清理安装时可能遗留的缓存文件
Type: filesandordirs; Name: "{app}\QtWebEngine"
Type: filesandordirs; Name: "{localappdata}\DraftSRTAssistant"
