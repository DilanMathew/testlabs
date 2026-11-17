; Inno Setup script - builds BethesdaLabs-Setup-<version>.exe
; Build:  iscc /DAppVersion=1.1.0 packaging\installer.iss   (after PyInstaller)

#ifndef AppVersion
  #define AppVersion "1.1.0"
#endif

[Setup]
AppId={{6A1F7C2E-3B5D-4C8E-9F21-B37A8D0E4C55}
AppName=Bethesda Labs
AppVersion={#AppVersion}
AppPublisher=Bethesda Labs Software
DefaultDirName={autopf}\Bethesda Labs
DefaultGroupName=Bethesda Labs
OutputDir=..\dist\installer
OutputBaseFilename=BethesdaLabs-Setup-{#AppVersion}
SetupIconFile=icon.ico
UninstallDisplayIcon={app}\BethesdaLabs.exe
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
Name: "{commonappdata}\BethesdaLabs"; Permissions: users-modify; Flags: uninsneveruninstall

[Files]
Source: "..\dist\BethesdaLabs\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\Bethesda Labs"; Filename: "{app}\BethesdaLabs.exe"
Name: "{group}\Bethesda Labs data folder"; Filename: "{commonappdata}\BethesdaLabs"
Name: "{group}\Uninstall Bethesda Labs"; Filename: "{uninstallexe}"
Name: "{autodesktop}\Bethesda Labs"; Filename: "{app}\BethesdaLabs.exe"; Tasks: desktopicon
Name: "{commonstartup}\Bethesda Labs"; Filename: "{app}\BethesdaLabs.exe"; Parameters: "--background"; Tasks: autostart

[Run]
Filename: "{app}\BethesdaLabs.exe"; Description: "Open Bethesda Labs now"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{cmd}"; Parameters: "/C taskkill /F /IM BethesdaLabs.exe"; Flags: runhidden; RunOnceId: "StopApp"

[Messages]
FinishedLabel=Bethesda Labs is installed.%n%nYour data is stored in C:\ProgramData\BethesdaLabs and is kept even if the software is uninstalled.
