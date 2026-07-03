from __future__ import annotations

import uuid
from datetime import datetime, timezone
from io import BytesIO

from fastapi.testclient import TestClient
from pypdf import PdfReader

from app.db.models import ExperimentRecord, ReportRecord
from app.db.session import SessionLocal
from app.main import app


SMALL_PNG_DATA_URL = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO6Wl8sAAAAASUVORK5CYII="
)


def test_report_pdf_export_returns_searchable_text_pdf():
    experiment_id = f"exp_pdf_{uuid.uuid4().hex[:8]}"
    report_id = f"report_{uuid.uuid4().hex[:8]}"

    db = SessionLocal()
    try:
        db.add(
            ExperimentRecord(
                id=experiment_id,
                name="PDF Test",
                file_name="demo.csv",
                sheet_name="CSV",
                target_column="value",
                recommended_model_id="naive",
                best_mae="12.3",
                model_count="1",
                config_json="{}",
                data_profile_json="{}",
                metrics_json="[]",
                backtest_json="{}",
                diagnostics_json="{}",
                series_json="[]",
                final_forecast_json=None,
                model_logs_json="[]",
                runtime_json=None,
                manifest_json=None,
                created_at=datetime.now(timezone.utc),
            )
        )
        db.add(
            ReportRecord(
                id=report_id,
                experiment_id=experiment_id,
                content_markdown=(
                    "# AI 预测总结报告\n\n"
                    "这是一份可复制文本的 PDF 报告。\n\n"
                    "## 关键发现\n\n"
                    "- MAE 下降到 12.30\n"
                    "- 协变量 Temperature 按 Static 处理\n"
                    "- Known Future Holiday 不会造成 Future Leakage\n"
                ),
                model="deepseek-v4-flash",
                created_at=datetime.now(timezone.utc),
            )
        )
        db.commit()
    finally:
        db.close()

    client = TestClient(app)
    response = client.post(
        f"/api/reports/{report_id}/pdf",
        json={
            "title": "实验报告 PDF",
            "visualArtifacts": [
                {
                    "id": "artifact_1",
                    "title": "图 1：回测概览",
                    "caption": "图像作为插图嵌入，正文与摘要保持为真实文本。",
                    "dataUrl": SMALL_PNG_DATA_URL,
                    "summary": ["图像说明 1", "图像说明 2"],
                }
            ],
        },
    )

    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("application/pdf")

    reader = PdfReader(BytesIO(response.content))
    extracted = "\n".join(page.extract_text() or "" for page in reader.pages)
    assert "AI 预测总结报告" in extracted
    assert "MAE 下降到 12.30" in extracted
    assert "Static" in extracted
    assert "图像说明 1" in extracted

    page_fonts = reader.pages[0]["/Resources"]["/Font"]
    embedded_true_type_found = False
    for font_ref in page_fonts.values():
        font = font_ref.get_object()
        descriptor = font.get("/FontDescriptor")
        if descriptor is None:
            continue
        descriptor_object = descriptor.get_object()
        if font.get("/Subtype") == "/TrueType" and (
            descriptor_object.get("/FontFile2") or descriptor_object.get("/FontFile3") or descriptor_object.get("/FontFile")
        ):
            embedded_true_type_found = True
            break
    assert embedded_true_type_found is True

    db = SessionLocal()
    try:
        report = db.get(ReportRecord, report_id)
        experiment = db.get(ExperimentRecord, experiment_id)
        if report is not None:
            db.delete(report)
        if experiment is not None:
            db.delete(experiment)
        db.commit()
    finally:
        db.close()
