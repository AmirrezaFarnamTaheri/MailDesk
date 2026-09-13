"""PyInstaller entry point for the MailDesk desktop application.

Keep the executable bootstrap outside the ``mailmerge_app`` package so importing
``mailmerge_app.desktop`` establishes the package context required by its relative
imports. Pointing PyInstaller directly at ``mailmerge_app/desktop.py`` executes that
module as ``__main__`` and leaves ``__package__`` unset, which breaks imports such as
``from .main import ...`` in the frozen executable.
"""

from mailmerge_app.desktop import main


if __name__ == "__main__":
    main()
