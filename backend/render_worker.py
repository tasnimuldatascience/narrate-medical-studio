"""Isolated PowerPoint rendering worker. Only sanitized PPTX input is accepted."""
import sys
from pathlib import Path
import pythoncom
import win32com.client

def main():
    source, output = map(Path, sys.argv[1:3])
    pythoncom.CoInitialize()
    app = deck = None
    try:
        app = win32com.client.DispatchEx('PowerPoint.Application')
        app.AutomationSecurity = 3  # msoAutomationSecurityForceDisable
        deck = app.Presentations.Open(str(source.resolve()), ReadOnly=True, Untitled=False, WithWindow=False)
        width = 1920
        height = round(width * deck.PageSetup.SlideHeight / deck.PageSetup.SlideWidth)
        output.mkdir(parents=True, exist_ok=True)
        for i in range(1, deck.Slides.Count + 1):
            deck.Slides(i).Export(str((output / f'slide-{i}.png').resolve()), 'PNG', width, height)
    finally:
        try:
            if deck is not None:
                deck.Close()
        finally:
            try:
                if app is not None:
                    app.Quit()
            finally:
                pythoncom.CoUninitialize()

if __name__ == '__main__':
    main()
