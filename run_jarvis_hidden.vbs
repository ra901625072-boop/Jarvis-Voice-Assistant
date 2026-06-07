Set WshShell = CreateObject("WScript.Shell")

' Open the web dashboard
WshShell.Run "http://localhost:8000"

' Run JARVIS backend silently in the background
WshShell.Run chr(34) & "d:\Jarvis\run_jarvis.bat" & Chr(34), 0

Set WshShell = Nothing
