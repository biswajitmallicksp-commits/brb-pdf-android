; BRB PDF - Windows installer (Inno Setup 6)
; Built automatically by .github/workflows/build-windows.yml
; Installs the ready program: Python is NOT needed on the computer.

#ifndef AppVersion
  #define AppVersion "0.5.0"
#endif

[Setup]
AppId={{6E1B7C52-8F3A-4D7E-9B21-3C5A2F0B7D11}
AppName=BRB PDF
AppVersion={#AppVersion}
AppVerName=BRB PDF {#AppVersion}
AppPublisher=BRB
DefaultDirName={autopf}\BRB PDF
DefaultGroupName=BRB PDF
DisableProgramGroupPage=yes
; installs for the current user without administrator rights (can choose "all users")
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir=..\output
OutputBaseFilename=BRB-PDF-Setup-{#AppVersion}
SetupIconFile=..\assets\app.ico
UninstallDisplayIcon={app}\PDFWorkbench.exe
UninstallDisplayName=BRB PDF
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ChangesAssociations=yes
CloseApplications=yes

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Shortcuts:"
Name: "pdfassoc"; Description: "Add BRB PDF to ""Open with"" for PDF files"; GroupDescription: "PDF files:"

[Files]
Source: "..\dist\PDFWorkbench\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\BRB PDF"; Filename: "{app}\PDFWorkbench.exe"
Name: "{autodesktop}\BRB PDF"; Filename: "{app}\PDFWorkbench.exe"; Tasks: desktopicon

[Registry]
; "Open with" entry for .pdf files (Windows lets the user choose the default app)
Root: HKA; Subkey: "Software\Classes\BRBPDF.Document"; ValueType: string; ValueName: ""; ValueData: "PDF Document"; Flags: uninsdeletekey; Tasks: pdfassoc
Root: HKA; Subkey: "Software\Classes\BRBPDF.Document\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\PDFWorkbench.exe,0"; Tasks: pdfassoc
Root: HKA; Subkey: "Software\Classes\BRBPDF.Document\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\PDFWorkbench.exe"" ""%1"""; Tasks: pdfassoc
Root: HKA; Subkey: "Software\Classes\.pdf\OpenWithProgids"; ValueType: string; ValueName: "BRBPDF.Document"; ValueData: ""; Flags: uninsdeletevalue; Tasks: pdfassoc
Root: HKA; Subkey: "Software\Classes\Applications\PDFWorkbench.exe"; ValueType: string; ValueName: "FriendlyAppName"; ValueData: "BRB PDF"; Flags: uninsdeletekey; Tasks: pdfassoc
Root: HKA; Subkey: "Software\Classes\Applications\PDFWorkbench.exe\SupportedTypes"; ValueType: string; ValueName: ".pdf"; ValueData: ""; Tasks: pdfassoc
Root: HKA; Subkey: "Software\Classes\Applications\PDFWorkbench.exe\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\PDFWorkbench.exe"" ""%1"""; Tasks: pdfassoc

[Run]
Filename: "{app}\PDFWorkbench.exe"; Description: "Start BRB PDF now"; Flags: nowait postinstall skipifsilent
