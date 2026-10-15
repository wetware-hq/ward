"""S14 replay flake root cause: figures stamped 'drawn <box clock, minute>' into the legends, so two runs either side
of a minute boundary differed. The harness now hands figures the scenario clock; the legend never shows the box clock."""
import re, tempfile
from stack import runner


def test_figure_legend_drawn_time_is_the_scenario_clock():
    h, art = runner.run("S14-oncology-results-au", tempfile.mkdtemp(), "en")
    got = re.findall(r"drawn (\d\d \w{3} \d{4} \d\d:\d\d)", art["legends"])
    import datetime
    d = datetime.datetime.fromisoformat(art["drawn"])
    assert d.year < 1940 and got and set(got) == {d.strftime("%d %b %Y %H:%M")}, got
