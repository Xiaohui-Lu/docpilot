"""Print what the offline demo provider extracts from each sample document (dev aid)."""

import glob
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from app.services.grounding import check_grounding  # noqa: E402
from app.services.llm.demo import DemoProvider  # noqa: E402

samples = pathlib.Path(__file__).resolve().parents[2] / "samples"
provider = DemoProvider()
for f in sorted(glob.glob(str(samples / "*.md"))):
    text = pathlib.Path(f).read_text(encoding="utf-8")
    ins = provider.extract(text, f).insights
    g = check_grounding(ins, text)
    print("==", pathlib.Path(f).name, ins.doc_type, ins.overall_risk)
    print("  parties:", [(x.name, x.role) for x in ins.parties])
    print("  dates:  ", [(d.label, d.date) for d in ins.key_dates])
    print("  amounts:", [(a.label, a.value, a.currency) for a in ins.amounts])
    print("  risks:  ", [(r.severity, r.title) for r in ins.risks], "grounding", g["score"])
    print("  summary:", ins.summary[:220])
