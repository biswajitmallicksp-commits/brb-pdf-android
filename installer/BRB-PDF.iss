; BRB PDF - Windows installer (Inno Setup 6)
; Built automatically by .github/workflows/build-windows.yml
; Installs the ready program: Python is NOT needed on the computer.

#ifndef AppVersion
  #define AppVersion "0.7.0"
#endif
; /DEdition=Lite builds the installer without the AI model
#ifdef Edition
  #define Suffix "-" + Edition
#else
  #define Suffix ""
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
OutputBaseFilename=BRB-PDF-Setup{#Suffix}-{#AppVersion}
SetupIconFile=..\assets\app.ico
UninstallDisplayIcon={app}\PDFWorkbench.exe
UninstallDisplayName=BRB PDF
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ChangesAssociations=yes
CloseApplications=yes
DiskSpanning=no

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Shortcuts:"
Name: "worddesktopicon"; Description: "Create a desktop shortcut for BRB PDF &Word (Word documents)"; GroupDescription: "Shortcuts:"
Name: "pdfassoc"; Description: "Add BRB PDF to ""Open with"" for PDF files"; GroupDescription: "PDF files:"
Name: "docxassoc"; Description: "Add BRB PDF Word to ""Open with"" for Word files (.docx)"; GroupDescription: "Word files:"

[Files]
Source: "..\dist\PDFWorkbench\*"; DestDir: "{app}"; Excludes: "\ai\models\*"; Flags: ignoreversion recursesubdirs createallsubdirs
#ifndef Edition
; the AI model is already compressed: store it as it is (much faster)
Source: "..\dist\PDFWorkbench\ai\models\*"; DestDir: "{app}\ai\models"; Flags: ignoreversion nocompression
#endif

[Icons]
Name: "{autoprograms}\BRB PDF"; Filename: "{app}\PDFWorkbench.exe"
Name: "{autodesktop}\BRB PDF"; Filename: "{app}\PDFWorkbench.exe"; Tasks: desktopicon
Name: "{autoprograms}\BRB PDF Word"; Filename: "{app}\PDFWorkbench.exe"; Parameters: "--word"; Comment: "New Word document"
Name: "{autodesktop}\BRB PDF Word"; Filename: "{app}\PDFWorkbench.exe"; Parameters: "--word"; Comment: "New Word document"; Tasks: worddesktopicon

[Registry]
; "Open with" entry for .pdf files (Windows lets the user choose the default app)
Root: HKA; Subkey: "Software\Classes\BRBPDF.Document"; ValueType: string; ValueName: ""; ValueData: "PDF Document"; Flags: uninsdeletekey; Tasks: pdfassoc
Root: HKA; Subkey: "Software\Classes\BRBPDF.Document\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\PDFWorkbench.exe,0"; Tasks: pdfassoc
Root: HKA; Subkey: "Software\Classes\BRBPDF.Document\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\PDFWorkbench.exe"" ""%1"""; Tasks: pdfassoc
Root: HKA; Subkey: "Software\Classes\.pdf\OpenWithProgids"; ValueType: string; ValueName: "BRBPDF.Document"; ValueData: ""; Flags: uninsdeletevalue; Tasks: pdfassoc
Root: HKA; Subkey: "Software\Classes\Applications\PDFWorkbench.exe"; ValueType: string; ValueName: "FriendlyAppName"; ValueData: "BRB PDF"; Flags: uninsdeletekey; Tasks: pdfassoc
Root: HKA; Subkey: "Software\Classes\Applications\PDFWorkbench.exe\SupportedTypes"; ValueType: string; ValueName: ".pdf"; ValueData: ""; Tasks: pdfassoc
Root: HKA; Subkey: "Software\Classes\Applications\PDFWorkbench.exe\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\PDFWorkbench.exe"" ""%1"""; Tasks: pdfassoc

; "Open with" entry for Word files
Root: HKA; Subkey: "Software\Classes\BRBPDF.WordDocument"; ValueType: string; ValueName: ""; ValueData: "Word Document"; Flags: uninsdeletekey; Tasks: docxassoc
Root: HKA; Subkey: "Software\Classes\BRBPDF.WordDocument\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\PDFWorkbench.exe,0"; Tasks: docxassoc
Root: HKA; Subkey: "Software\Classes\BRBPDF.WordDocument\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\PDFWorkbench.exe"" ""%1"""; Tasks: docxassoc
Root: HKA; Subkey: "Software\Classes\.docx\OpenWithProgids"; ValueType: string; ValueName: "BRBPDF.WordDocument"; ValueData: ""; Flags: uninsdeletevalue; Tasks: docxassoc
Root: HKA; Subkey: "Software\Classes\Applications\PDFWorkbench.exe\SupportedTypes"; ValueType: string; ValueName: ".docx"; ValueData: ""; Tasks: docxassoc

[Run]
Filename: "{app}\PDFWorkbench.exe"; Description: "Start BRB PDF now"; Flags: nowait postinstall skipifsilent
