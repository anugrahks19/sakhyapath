from __future__ import annotations

from html import escape
from io import BytesIO

from reportlab.graphics.shapes import Circle, Drawing, Line, String
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


INK = colors.HexColor("#17324D")
BLUE = colors.HexColor("#3569D8")
MUTED = colors.HexColor("#60738B")
PALE = colors.HexColor("#EDF3FD")
AMBER = colors.HexColor("#BF772C")


def _text(value: object) -> str:
    return escape("" if value is None else str(value))


def _schematic_map(observations: list[dict]) -> Drawing:
    width, height = 490, 172
    drawing = Drawing(width, height)
    drawing.add(String(8, height - 15, "OBSERVED CAMERA LOCATIONS", fontName="Helvetica-Bold",
                       fontSize=8, fillColor=MUTED))
    drawing.add(String(8, 5, "Schematic geographic positions. Dashed links are inferred, not roads.",
                       fontName="Helvetica", fontSize=7, fillColor=MUTED))
    if not observations:
        drawing.add(String(8, 80, "No verified-evidence observations for this query.",
                           fontName="Helvetica", fontSize=10, fillColor=MUTED))
        return drawing
    latitudes = [item["latitude"] for item in observations]
    longitudes = [item["longitude"] for item in observations]
    min_lat, max_lat = min(latitudes), max(latitudes)
    min_lon, max_lon = min(longitudes), max(longitudes)
    range_lat = max(max_lat - min_lat, .05)
    range_lon = max(max_lon - min_lon, .05)
    points = []
    for item in observations:
        x = 36 + (item["longitude"] - min_lon) / range_lon * (width - 72)
        y = 29 + (item["latitude"] - min_lat) / range_lat * (height - 58)
        points.append((x, y))
    for (x1, y1), (x2, y2) in zip(points, points[1:]):
        drawing.add(Line(x1, y1, x2, y2, strokeColor=BLUE,
                         strokeWidth=1.2, strokeDashArray=[4, 4]))
    for index, (x, y) in enumerate(points, 1):
        drawing.add(Circle(x, y, 9, fillColor=BLUE, strokeColor=colors.white, strokeWidth=2))
        drawing.add(String(x, y - 2.5, str(index), fontName="Helvetica-Bold", fontSize=7,
                           textAnchor="middle", fillColor=colors.white))
    return drawing


def build_report(journey: dict) -> bytes:
    """Render exactly the journey payload returned by the API; no second query."""
    pursuit = journey["pursuit"]
    styles = getSampleStyleSheet()
    title = ParagraphStyle("SakhyaTitle", parent=styles["Title"], fontName="Helvetica-Bold",
                           fontSize=21, leading=26, textColor=INK, spaceAfter=8)
    section = ParagraphStyle("SakhyaSection", parent=styles["Heading2"],
                             fontName="Helvetica-Bold", fontSize=11, leading=15,
                             textColor=INK, spaceBefore=14, spaceAfter=6)
    body = ParagraphStyle("SakhyaBody", parent=styles["BodyText"], fontName="Helvetica",
                          fontSize=8.5, leading=12, textColor=INK, spaceAfter=5)
    small = ParagraphStyle("SakhyaSmall", parent=body, fontSize=7.2, leading=10,
                           textColor=MUTED, spaceAfter=3)
    note = ParagraphStyle("SakhyaNote", parent=body, fontSize=8, leading=11,
                          textColor=AMBER, spaceAfter=5)
    bytes_out = BytesIO()
    doc = SimpleDocTemplate(bytes_out, pagesize=(210 * mm, 297 * mm),
                            leftMargin=17 * mm, rightMargin=17 * mm,
                            topMargin=18 * mm, bottomMargin=19 * mm,
                            title=f"SakhyaPath Evidence Journey - {pursuit['target_plate']}",
                            author="SakhyaPath local prototype")
    story = [Paragraph("SakhyaPath", small),
             Paragraph("Evidence Journey", title),
             Paragraph(f"Registration <b>{_text(pursuit['target_plate'])}</b> | "
                       f"Pursuit {_text(pursuit['id'])}", body),
             Paragraph(f"Created {_text(pursuit['created_utc'])} | "
                       f"Scope {_text(pursuit['department_scope'] or 'operator-wide')}", small),
             Spacer(1, 5)]
    counts = journey["counts"]
    summary = Table([
        ["Records", "Supported observations", "Candidates", "Rejected"],
        [str(counts["records"]), str(counts["observations"]),
         str(counts["candidates"]), str(counts["rejected"])],
    ], colWidths=[120, 140, 110, 110])
    summary.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), PALE),
        ("TEXTCOLOR", (0, 0), (-1, -1), INK),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("LINEBELOW", (0, -1), (-1, -1), .5, colors.HexColor("#DAE5F2")),
    ]))
    story += [summary, Spacer(1, 12), _schematic_map(journey["observations"]),
              Paragraph("Time and inference contract", section),
              Paragraph("Source PTS is a per-stream media clock. A timestamp marked approximate "
                        "is a receive-time diagnostic, not a verified event time. An attested "
                        "PTS-to-UTC mapping is used only for the matching stream generation. "
                        "Straight dashed links are possible connections, not observed travel or road routes.", body)]
    for gap in journey["gaps"]:
        story.append(Paragraph(f"Gap: {_text(gap)}", note))
    story.append(Paragraph("Observed and reviewed records", section))
    if not journey["records"]:
        story.append(Paragraph("No historical sightings matched this query.", body))
    for index, item in enumerate(journey["records"], 1):
        source = "Government" if item["source_system"] == "sentinel" else "Owned"
        timestamp_label = ("operator-attested mapped UTC" if item["event_utc_if_verified"]
                           else "approximate receive UTC")
        header = (f"{index}. {_text(item['camera_id'])} - {_text(item['effective_plate'])} "
                  f"({_text(item['effective_status'])})")
        detail = (
            f"{_text(item['display_name'])} | {_text(item['department'])} | "
            f"{source} / {_text(item['source_mode'])}<br/>"
            f"Location: {item['latitude']:.5f}, {item['longitude']:.5f} | "
            f"{_text(timestamp_label)}: {_text(item['display_time_utc'])}<br/>"
            f"Raw OCR: {_text(item['raw_text'])} | Normalized: {_text(item['plate_normalized'])} | "
            f"PTS: {_text(item['source_pts'])} ({_text(item['pts_timebase'])}), "
            f"generation {item['stream_generation']}<br/>"
            f"Detector {item['detector_score']:.3f} | OCR {item['ocr_score']:.3f} | "
            f"Model {_text(item['model_version'])}<br/>"
            f"Evidence: {_text(item['evidence_status'])} | SHA-256: "
            f"{_text(item['evidence_sha256'][:32])}<br/>{_text(item['evidence_sha256'][32:])}"
        )
        story.append(KeepTogether([Paragraph(header, section), Paragraph(detail, body)]))
        if item["review_history"]:
            for review in item["review_history"]:
                story.append(Paragraph(
                    f"Review {_text(review['reviewed_utc'])}: {_text(review['decision'])} "
                    f"by {_text(review['actor'])}; corrected plate "
                    f"{_text(review['corrected_plate'] or 'none')}; note {_text(review['note'])}",
                    small,
                ))
        if not item["evidence_supported"]:
            story.append(Paragraph("This record is excluded from supported map observations "
                                   "until its evidence is restored and verified.", note))
    story.append(Paragraph("Inferred connections", section))
    if not journey["links"]:
        story.append(Paragraph("No supported pair of observations to connect.", body))
    for link in journey["links"]:
        duration = (f"{link['verified_duration_seconds']:.1f} s mapped "
                    f"(+/- {link['duration_uncertainty_seconds']:.1f} s)" if
                    link["verified_duration_seconds"] is not None else "time unaligned")
        speed = (f"; minimum {link['minimum_required_speed_kmh']:.1f} km/h" if
                 link["minimum_required_speed_kmh"] is not None else "")
        story.append(Paragraph(
            f"{_text(link['from_camera_id'])} to {_text(link['to_camera_id'])}: "
            f"{link['distance_km_straight_line']:.2f} km straight-line; {duration}{speed}; "
            f"<b>{_text(link['status'])}</b>. Dashed inference only.", body,
        ))
    story.append(Paragraph("Watchlist alerts", section))
    if not journey["alerts"]:
        story.append(Paragraph("No watchlist alerts linked to these sightings.", body))
    for alert in journey["alerts"]:
        story.append(Paragraph(
            f"{_text(alert['id'])}: sighting {_text(alert['sighting_id'])}, "
            f"{_text(alert['match_basis'])}, {_text(alert['status'])}, "
            f"created {_text(alert['created_utc'])}, acknowledged by "
            f"{_text(alert['acknowledged_by'] or 'none')}.", body,
        ))

    active = journey.get("active_pursuit") or {}
    story.append(Paragraph("Active Pursuit schedule", section))
    if not active.get("schedule"):
        story.append(Paragraph("No measured-budget Active Pursuit schedule has been started.", body))
    else:
        run = active["schedule"]
        story.append(Paragraph(
            f"Revision {run['revision']} | {_text(run['created_utc'])} | "
            f"budget {run['budget_fps']:.2f} fps including 30% headroom | "
            f"external workers reserved {run['reserved_fps']:.2f} fps. "
            f"Reason: {_text(run['reason'])}.", body,
        ))
        for allocation in active["allocations"]:
            story.append(Paragraph(
                f"{_text(allocation['camera_id'])}: requested "
                f"{allocation['requested_fps']:.3f} fps, worker acknowledged "
                f"{allocation['applied_fps']:.3f} fps, current "
                f"{allocation['current_applied_fps']:.3f} fps; "
                f"{_text(allocation['allocation_reason'])}.", small,
            ))
    coverage = journey.get("coverage") or {}
    coverage_intro = Paragraph(
        "Window clock is operational server UTC. 'Not observed in sampled frames' "
        "does not prove the target was absent. Planned frames derive from a "
        "worker-acknowledged rate; actual analyzed frames determine coverage.", body)

    def coverage_paragraph(window: dict) -> Paragraph:
        return Paragraph(
            f"Revision {window['revision']} | {_text(window['camera_id'])} | "
            f"{_text(window['window_start_utc'])} to {_text(window['window_end_utc'])}<br/>"
            f"<b>{_text(window['result_code'])}</b> - {_text(window['reason'])}. "
            f"Planned {window['planned_frames']}; received {window['received_frames']}; "
            f"analyzed {window['analyzed_frames']}; capture/decode exceptions "
            f"{window['decode_errors']}; health {_text(window['health'])}.", body)

    windows = coverage.get("windows", [])
    first_window = coverage_paragraph(windows[0]) if windows else Paragraph(
        "No coverage windows recorded.", body)
    story.append(KeepTogether([
        Paragraph("Coverage Integrity Ledger", section), coverage_intro, first_window,
    ]))
    for window in windows[1:]:
        story.append(coverage_paragraph(window))

    def page_footer(canvas, page_doc):
        canvas.saveState()
        canvas.setStrokeColor(colors.HexColor("#DAE5F2"))
        canvas.line(17 * mm, 15 * mm, 193 * mm, 15 * mm)
        canvas.setFillColor(MUTED)
        canvas.setFont("Helvetica", 7)
        canvas.drawString(17 * mm, 11 * mm, "SakhyaPath | Evidence-backed local prototype")
        canvas.drawRightString(193 * mm, 11 * mm, f"Page {page_doc.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=page_footer, onLaterPages=page_footer)
    return bytes_out.getvalue()
