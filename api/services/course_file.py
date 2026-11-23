"""Course-file report as a PDF (phase 10, FR-6.6).

One PDF per offering, built only from what the database holds: the rule version used, the
assessments, CO attainment (direct, survey, final) with a chart, PO attainment with a chart, the
COs below target with their likely upstream causes, how many students are below target, and the
improvement actions. Drawn with PyMuPDF (already used for OCR). Text uses FiraGO, an open-licence
Unicode font from pymupdf-fonts, embedded in the PDF, so CO statements, names and actions with
symbols (>=), curly quotes or Devanagari come out as written; a character FiraGO lacks is shown as
"?". The layout is plain and fixed; a college template can replace `render` without touching `gather`.
"""

from datetime import datetime, timezone

import fitz

A4_W, A4_H = 595.0, 842.0
MARGIN = 48.0
INK, MUTED, RULE = (0.07, 0.08, 0.09), (0.36, 0.37, 0.38), (0.85, 0.86, 0.87)
ACCENT, WARN, LIGHT = (0.106, 0.424, 0.502), (0.77, 0.40, 0.18), (0.94, 0.95, 0.96)
FONT, BOLD = "figo", "figbo"              # FiraGO regular and bold (pymupdf-fonts), embedded per page
_FONTS: dict[str, fitz.Font] = {}


def _font(name: str) -> fitz.Font:
    if name not in _FONTS:
        _FONTS[name] = fitz.Font(name)
    return _FONTS[name]


def _clean(text, font: str = FONT) -> str:
    """The text with any character the font cannot draw replaced by '?' (instead of a blank box)."""
    f = _font(font)
    return "".join(ch if ch in "\n " or f.has_glyph(ord(ch)) else "?" for ch in str(text))


def _length(text: str, font: str, size: float) -> float:
    return _font(font).text_length(text, fontsize=size)


class NoResults(ValueError):
    """The offering has no computed attainment to report."""


# ---------------------------------------------------------------- data

def gather(conn, offering_id: int) -> dict:
    """Everything the report shows, read through the caller's session (RLS applies)."""
    from api.routers.offerings import attainment

    head = conn.execute("""
        SELECT o.offering_id, c.code, c.title, c.semester, o.academic_year, o.term, o.section, f.name AS faculty,
               (SELECT count(*) FROM enrollment e WHERE e.offering_id = o.offering_id) AS enrolled
        FROM course_offering o JOIN course c USING (course_id) JOIN faculty f ON f.faculty_id = o.faculty_id
        WHERE o.offering_id = %s AND fn_can_view_offering(o.offering_id)""", (offering_id,)).fetchone()
    if not head:
        raise LookupError("Offering not found")
    att = attainment(conn, offering_id)
    if not att["cos"]:
        raise NoResults("Compute attainment first; the course file reports the computed results")
    config_id = att["cos"][0]["config_id"]
    rules = conn.execute("""
        SELECT c.*, (SELECT string_agg(replace(replace(replace(component::text, 'CIE_THEORY', 'CIE theory'),
                                                             'CIE_QUIZ', 'CIE quiz'), '_', ' ')
                                     || ' ' || round(weight_pct)::text, ', '
                                     ORDER BY array_position(ARRAY['CIE_THEORY','CIE_QUIZ','EL','SEE']::assessment_component[], component))
                     FROM config_component_weight w WHERE w.config_id = c.config_id) AS components
        FROM attainment_config c WHERE c.config_id = %s""", (config_id,)).fetchone()
    assessments = conn.execute("""
        SELECT a.name, a.type, a.max_marks, a.locked_at,
               (SELECT count(*) FROM assessment_question q WHERE q.assessment_id = a.assessment_id) AS questions
        FROM assessment a WHERE a.offering_id = %s
        ORDER BY array_position(ARRAY['CIE_THEORY','CIE_QUIZ','EL','SEE']::assessment_component[], a.type), a.name""",
                               (offering_id,)).fetchall()
    below_target = {r["co_id"]: r["n"] for r in conn.execute("""
        SELECT s.co_id, count(*) FILTER (WHERE s.pct < %s) AS n
        FROM student_co_score s WHERE s.offering_id = %s GROUP BY s.co_id""", (rules["target_pct"], offering_id))}
    weak = [c for c in att["cos"] if float(c["final_level"]) < float(c["target"])]
    causes = {}
    for c in weak:
        rows = conn.execute("SELECT * FROM fn_root_cause(%s, %s) WHERE passes ORDER BY likely_cause_rank LIMIT 2",
                            (offering_id, c["co_id"])).fetchall()
        causes[c["co_id"]] = rows
    actions = [a for a in att["actions"] if a["offering_id"] == offering_id]
    return {"head": head, "rules": rules, "assessments": assessments, "cos": att["cos"], "pos": att["pos"],
            "map": att["map"], "weak": weak, "causes": causes, "below_target": below_target, "actions": actions,
            "generated": datetime.now(timezone.utc)}


# ---------------------------------------------------------------- layout

def _fmt(v, digits=2) -> str:
    return "-" if v is None else f"{float(v):.{digits}f}"


def _wrap(text: str, width: float, size: float, font: str = FONT) -> list[str]:
    lines, line = [], ""
    for word in _clean(text, font).split():
        trial = f"{line} {word}".strip()
        if _length(trial, font, size) <= width or not line:
            line = trial
        else:
            lines.append(line)
            line = word
    return lines + ([line] if line else [])


class _Writer:
    def __init__(self, title: str):
        self.doc = fitz.open()
        self.title = title
        self.page = None
        self.y = 0.0
        self._new_page()

    def _new_page(self):
        self.page = self.doc.new_page(width=A4_W, height=A4_H)
        for name in (FONT, BOLD):
            self.page.insert_font(fontname=name, fontbuffer=_font(name).buffer)
        self.y = MARGIN

    def need(self, h: float):
        if self.y + h > A4_H - MARGIN - 18:
            self._new_page()

    def text(self, s: str, size=10.0, font=FONT, color=INK, gap=4.0, width=None, x=MARGIN):
        lines = _wrap(s, width or (A4_W - 2 * MARGIN), size, font)
        for ln in lines:
            self.need(size * 1.35)
            self.page.insert_text((x, self.y + size), ln, fontsize=size, fontname=font, color=color)
            self.y += size * 1.35
        self.y += gap

    def heading(self, s: str):
        self.need(40)
        self.y += 8
        self.text(s, 13, BOLD, gap=2)
        self.page.draw_line((MARGIN, self.y), (A4_W - MARGIN, self.y), color=RULE, width=0.6)
        self.y += 8

    def table(self, cols: list[tuple[str, float, str]], rows: list[list[str]], size=8.5):
        """cols: (header, width share, 'l' or 'r'). Long cells wrap; the header repeats on a new page."""
        total = A4_W - 2 * MARGIN
        widths = [w * total for _, w, _ in cols]

        header = [c for c, _, _ in cols]

        def draw_row(cells, font, fill=None):
            wrapped = [_wrap(c, w - 8, size, font) or [""] for c, w in zip(cells, widths)]
            h = max(len(w) for w in wrapped) * size * 1.3 + 6
            page = self.page
            self.need(h)
            if self.page is not page and cells is not header:   # continued on a new page: header again
                draw_row(header, BOLD, LIGHT)
            if fill:
                self.page.draw_rect(fitz.Rect(MARGIN, self.y, A4_W - MARGIN, self.y + h), color=None, fill=fill)
            x = MARGIN
            for lines, w, (_, _, align) in zip(wrapped, widths, cols):
                for i, ln in enumerate(lines):
                    tx = x + 4 if align == "l" else x + w - 4 - _length(ln, font, size)
                    self.page.insert_text((tx, self.y + 3 + size + i * size * 1.3), ln, fontsize=size,
                                          fontname=font, color=INK)
                x += w
            self.y += h
            self.page.draw_line((MARGIN, self.y), (A4_W - MARGIN, self.y), color=RULE, width=0.4)
            return h

        draw_row(header, BOLD, LIGHT)
        for r in rows:
            draw_row(r, FONT)
        self.y += 8

    def bars(self, items: list[tuple[str, float, float]], top: float = 3.0, caption: str = ""):
        """Horizontal bars (label, value, target) on a 0..top scale, target marked."""
        row, label_w = 16.0, 70.0
        h = len(items) * row + 26
        self.need(h)
        x0 = MARGIN + label_w
        span = A4_W - 2 * MARGIN - label_w - 40
        for t in range(int(top) + 1):
            gx = x0 + span * t / top
            self.page.draw_line((gx, self.y), (gx, self.y + len(items) * row), color=RULE, width=0.4)
            self.page.insert_text((gx - 3, self.y + len(items) * row + 10), str(t), fontsize=7, fontname=FONT, color=MUTED)
        for i, (label, value, target) in enumerate(items):
            y = self.y + i * row
            self.page.insert_text((MARGIN, y + 11), _clean(label), fontsize=8.5, fontname=FONT, color=INK)
            w = span * max(0.0, min(value, top)) / top
            colour = ACCENT if value >= target else WARN
            if w > 0:
                self.page.draw_rect(fitz.Rect(x0, y + 3, x0 + w, y + row - 3), color=None, fill=colour)
            self.page.insert_text((x0 + w + 4, y + 11), f"{value:.2f}", fontsize=8, fontname=FONT, color=INK)
            tx = x0 + span * min(target, top) / top
            self.page.draw_line((tx, y + 1), (tx, y + row - 1), color=INK, width=1.2, dashes="[2 2] 0")
        self.y += len(items) * row + 16
        if caption:
            self.text(caption, 7.5, color=MUTED, gap=6)

    def finish(self) -> bytes:
        n = len(self.doc)
        for i, page in enumerate(self.doc, start=1):
            page.insert_text((MARGIN, A4_H - MARGIN + 18), _clean(self.title), fontsize=7.5, fontname=FONT, color=MUTED)
            label = f"Page {i} of {n}"
            page.insert_text((A4_W - MARGIN - _length(label, FONT, 7.5), A4_H - MARGIN + 18),
                             label, fontsize=7.5, fontname=FONT, color=MUTED)
        self.doc.subset_fonts()           # keep only the glyphs used (about 850 KB down to tens of KB)
        return self.doc.tobytes(deflate=True, garbage=3)


def render(d: dict) -> bytes:
    h, r = d["head"], d["rules"]
    term = "odd" if h["term"] == "odd" else "even"
    title = f"{h['code']} {h['title']} - course file, {h['academic_year']} {term} term, section {h['section']}"
    w = _Writer(title)
    w.text(f"{h['code']} {h['title']}", 18, BOLD, gap=2)
    w.text(f"Course file - {h['academic_year']}, {term} term, section {h['section']} - {h['faculty']} - "
           f"{h['enrolled']} students", 10.5, color=MUTED, gap=2)
    w.text(f"Generated {d['generated']:%d %b %Y, %H:%M} UTC from the computed results "
           f"({d['cos'][0]['computed_at']:%d %b %Y}) by the CO-PO Attainment System.", 8.5, color=MUTED, gap=10)

    w.heading("Rules used")
    w.text(f"Rule version {r['config_id']} (valid from {r['valid_from']:%d %b %Y}). A student attains a CO with a score "
           f"of at least {_fmt(r['target_pct'], 0)}%. Level 3 if at least {_fmt(r['l3_pct'], 0)}% of students attain it, "
           f"2 if {_fmt(r['l2_pct'], 0)}%, 1 if {_fmt(r['l1_pct'], 0)}%, else 0. Final level = "
           f"{_fmt(r['direct_weight'], 0)}% direct + {_fmt(r['indirect_weight'], 0)}% survey. "
           f"Targets: CO {_fmt(r['co_target_level'])}, PO {_fmt(r['po_target_level'])}. "
           f"Component weights: {r['components']}.", 9.5)

    w.heading("Assessments")
    w.table([("Assessment", 0.34, "l"), ("Component", 0.22, "l"), ("Questions", 0.12, "r"), ("Max marks", 0.14, "r"),
             ("Locked", 0.18, "r")],
            [[a["name"], a["type"].replace("_", " ").title().replace("Cie", "CIE").replace("See", "SEE").replace("El", "EL"),
              str(a["questions"]), _fmt(a["max_marks"], 0), f"{a['locked_at']:%d %b %Y}" if a["locked_at"] else "open"]
             for a in d["assessments"]])

    w.heading("CO attainment")
    w.table([("CO", 0.07, "l"), ("Statement", 0.37, "l"), ("Attained", 0.11, "r"), ("Direct", 0.09, "r"),
             ("Survey", 0.09, "r"), ("Final", 0.09, "r"), ("Target", 0.09, "r"), ("Met", 0.09, "l")],
            [[f"CO{c['co_number']}", c["statement"], f"{_fmt(c['pct_attained'], 1)}%", str(c["direct_level"]),
              str(c["indirect_level"]), _fmt(c["final_level"]), _fmt(c["target"]),
              "yes" if float(c["final_level"]) >= float(c["target"]) else "no"] for c in d["cos"]])
    w.bars([(f"CO{c['co_number']}", float(c["final_level"]), float(c["target"])) for c in d["cos"]],
           caption="Final CO level (0-3); the dashed mark is the target. Teal meets the target, orange does not.")

    if any(c["respondents"] for c in d["cos"]):
        w.heading("Course-exit survey")
        w.table([("CO", 0.15, "l"), ("Respondents", 0.25, "r"), ("Favourable ratings", 0.3, "r"), ("Survey level", 0.3, "r")],
                [[f"CO{c['co_number']}", str(c["respondents"] or 0), f"{_fmt(c['pct_favourable'], 1)}%",
                  str(c["indirect_level"])] for c in d["cos"]])

    w.heading("PO attainment")
    mapped = {}
    for m in d["map"]:
        mapped.setdefault(m["po_id"], []).append(m)
    co_no = {c["co_id"]: c["co_number"] for c in d["cos"]}
    w.table([("PO", 0.1, "l"), ("Statement", 0.42, "l"), ("Mapped COs (strength)", 0.24, "l"), ("Value", 0.12, "r"),
             ("Target", 0.12, "r")],
            [[p["code"], p["statement"], ", ".join(f"CO{co_no.get(m['co_id'], '?')} ({m['strength']})"
                                                   for m in mapped.get(p["po_id"], [])),
              _fmt(p["attainment"]), _fmt(p["target"])] for p in d["pos"]])
    w.bars([(p["code"], float(p["attainment"]), float(p["target"])) for p in d["pos"]],
           caption="PO value for this offering (0-3); the dashed mark is the target.")

    w.heading("COs below target")
    if not d["weak"]:
        w.text("Every CO met its target.", 9.5)
    for c in d["weak"]:
        n = d["below_target"].get(c["co_id"], 0)
        w.text(f"CO{c['co_number']}: final level {_fmt(c['final_level'])} against a target of {_fmt(c['target'])}; "
               f"{n} of {c['students']} students scored below {_fmt(r['target_pct'], 0)}%.", 9.5, BOLD, gap=2)
        causes = d["causes"].get(c["co_id"], [])
        if causes:
            for k in causes:
                w.text(f"Likely upstream cause: {k['up_course_code']} CO{k['up_co_number']} ({k['up_statement']}), "
                       f"{k['depth']} step{'s' if k['depth'] > 1 else ''} back, correlation r = {_fmt(k['correlation'])} over "
                       f"{k['n']} students.", 9, x=MARGIN + 12, width=A4_W - 2 * MARGIN - 12, gap=2)
        else:
            w.text("No upstream CO shows a strong enough link to name a likely cause.", 9, color=MUTED,
                   x=MARGIN + 12, width=A4_W - 2 * MARGIN - 12, gap=2)
        w.y += 4
    w.text("Root-cause findings are correlations between the same students' scores, evidence for review rather than proof.",
           7.5, color=MUTED, gap=6)

    w.heading("Improvement actions")
    if d["actions"]:
        w.table([("CO", 0.08, "l"), ("Action", 0.58, "l"), ("Source", 0.14, "l"), ("Status", 0.2, "l")],
                [[f"CO{a['co_number']}", a["description"], a["source"], a["status"]] for a in d["actions"]])
    else:
        w.text("No improvement actions were recorded for this offering.", 9.5)
    return w.finish()
