import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def pytest_terminal_summary(terminalreporter):
    from stack import paths, locales
    if paths.TRUTH is None:
        terminalreporter.write_line(locales.line(paths.NOT_RUN))
