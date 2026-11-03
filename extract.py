import re, sys, json
from bs4 import BeautifulSoup
soup = BeautifulSoup(open("p.html", encoding="utf-8").read(), "html.parser")
for m in soup.find_all("math"):
    m.replace_with(" $" + (m.get("alttext") or "") + "$ ")
for t in soup.select("section.ltx_bibliography, nav, header, footer, script, style"):
    t.decompose()
paras = []
sec = ""
for el in soup.find_all(["h2", "h3", "h4", "p", "figcaption", "li", "td"]):
    txt = re.sub(r"\s+", " ", el.get_text(" ", strip=True))
    if el.name in ("h2", "h3", "h4"):
        sec = txt[:80]
        continue
    if len(txt) > 40:
        paras.append((sec, txt))
groups = {
    "g1_laziness": r"lazy|laziness|activation norm|embedding norm|attention (ratio|share|fraction|mass)|wrapper|<img>|image token|read ?out|diagnos",
    "g2_compute": r"GPU|H100|A100|H200|GB200|node|hours|FLOP|compute budget|petaflop|cluster|accelerator",
    "g3_lr": r"learning rate|warm-?up|cosine|re-?initiali|schedule|optimizer|AdamW",
    "g4_lambda": r"loss weight|\\lambda|weighted|diffusion loss.*(weight|coefficient)|coefficient",
}
for g, pat in groups.items():
    hits = [f"[{s}] {t}" for s, t in paras if re.search(pat, t, re.I)]
    out = "\n\n".join(hits)[:36000]
    open(g + ".txt", "w").write(out or "(no match)")
