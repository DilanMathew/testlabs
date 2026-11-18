; Inno Setup script - builds BalajiXRays-Setup-<version>.exe
; Build:  iscc /DAppVersion=1.1.0 packaging\installer.iss   (after PyInstaller)

#ifndef AppVersion
  #define AppVersion "1.1.0"
#endif

[Setup]
AppId={{6A1F7C2E-3B5D-4C8E-9F21-B37A8D0E4C55}
AppName=Balaji X Rays
AppVersion={#AppVersion}
AppPublisher=Balaji X Rays
DefaultDirName={autopf}\Balaji X Rays
DefaultGroupName=Balaji X Rays
OutputDir=..\dist\installer
OutputBaseFilename=BalajiXRays-Setup-{#AppVersion}
SetupIconFile=icon.ico
UninstallDisplayIcon={app}\BalajiXRays.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=force

[Tasks]
Name: "desktopicon"; Description: "Create a desktop icon"; GroupDescription: "Shortcuts:"
Name: "autostart"; Description: "Start automatically when Windows starts (recommended - keeps daily backups running)"; GroupDescription: "Start-up:"

[Dirs]
; Shared data folder, writable by every Windows user of this PC. Never removed on uninstall.
Name: "{commonappdata}\BalajiXRays"; Permissions: users-modify; Flags: uninsneveruninstall

[Files]
Source: "..\dist\BalajiXRays\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\Balaji X Rays"; Filename: "{app}\BalajiXRays.exe"
Name: "{group}\Balaji X Rays data folder"; Filename: "{commonappdata}\BalajiXRays"
Name: "{group}\Uninstall Balaji X Rays"; Filename: "{uninstallexe}"
Name: "{autodesktop}\Balaji X Rays"; Filename: "{app}\BalajiXRays.exe"; Tasks: desktopicon
Name: "{commonstartup}\Balaji X Rays"; Filename: "{app}\BalajiXRays.exe"; Parameters: "--background"; Tasks: autostart

[Run]
Filename: "{app}\BalajiXRays.exe"; Description: "Open Balaji X Rays now"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{cmd}"; Parameters: "/C taskkill /F /IM BalajiXRays.exe"; Flags: runhidden; RunOnceId: "StopApp"

[Messages]
FinishedLabel=Balaji X Rays is installed.%n%nYour data is stored in C:\ProgramData\BalajiXRays and is kept even if the software is uninstalled.
