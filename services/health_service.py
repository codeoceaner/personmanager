# -*- coding: utf-8 -*-
"""健康服务：健康档案（1:1 人员）、日常监测 8 项两级预警、体检报告归档与解析。

阈值取自 sys_config.health_thresholds（超级用户在系统设置中调整），未配置时回退
config.HEALTH_INDICATORS：
    高于正常 → 黄色预警，继续升高 → 红色报警；低于正常类指标方向相反。
总体级别取最严重项：红 > 黄 > 正常。
"""

import datetime
import json
import re
import shutil
from pathlib import Path

import config
from db import database
from services import personnel_service, platform_service

_CHECK_COLUMNS = {key for key, _label, _unit in config.MONITOR_FIELDS}

# 标准模板体检报告的关键信息（非标准模板 / 扫描件匹配不到时返回空）
_PATTERNS = {
    "height_cm": r"身高[^\d]{0,8}(\d{2,3}(?:\.\d)?)",
    "weight_kg": r"体重[^\d]{0,8}(\d{2,3}(?:\.\d)?)",
    "hba1c": r"糖化血红蛋白[^\d]{0,8}(\d{1,2}(?:\.\d)?)",
}
_BLOOD_RE = re.compile(r"血型[^\w]{0,8}(AB|A|B|O)")
_RH_RE = re.compile(r"[Rr][Hh][^\w]{0,6}(阳性|阴性|[＋+\-－])")
_ORG_RE = re.compile(r"(?:体检机构|体检单位|医疗机构|体检医院)[：:\s]*([^\n]{2,40})")
_DATE_RE = re.compile(r"(20\d{2})\s*[-年/.]\s*(\d{1,2})\s*[-月/.]\s*(\d{1,2})")


# ---------------------------------------------------------------- 基础工具
def _to_float(value):
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def calc_bmi(height_cm, weight_kg):
    """BMI = 体重(kg) / 身高(m)²；缺项返回 None。"""
    height = _to_float(height_cm)
    weight = _to_float(weight_kg)
    if not height or not weight or height <= 0 or weight <= 0:
        return None
    return round(weight / ((height / 100) ** 2), 1)


def thresholds():
    """当前生效的健康指标阈值（系统设置保存后立即生效）。"""
    raw = database.get_config("health_thresholds")
    try:
        data = json.loads(raw) if raw else None
    except (TypeError, ValueError):
        data = None
    if not isinstance(data, list) or not data:
        return [dict(item) for item in config.HEALTH_INDICATORS]
    return [dict(item) for item in data]


def _level_of(indicator, value):
    if indicator.get("direction") == "low_bad":
        if value < indicator["red_max"]:
            return "红色报警"
        if value < indicator["normal_min"]:
            return "黄色预警"
        return "正常"
    if value >= indicator["red_min"]:
        return "红色报警"
    if value > indicator["normal_max"]:
        return "黄色预警"
    return "正常"


def evaluate_indicators(values):
    """按阈值评估指标。返回 (总体级别, 异常项列表)。"""
    items = []
    for indicator in thresholds():
        number = _to_float(values.get(indicator["key"]))
        if number is None:
            continue
        level = _level_of(indicator, number)
        if level == "正常":
            continue
        items.append({
            "key": indicator["key"], "label": indicator["label"], "level": level,
            "text": f"{indicator['label']} {number:g}{indicator['unit']}",
        })
    if any(item["level"] == "红色报警" for item in items):
        return "红色报警", items
    return ("黄色预警", items) if items else ("正常", items)


# ---------------------------------------------------------------- 体检到期
def checkup_level(last_checkup_date):
    """体检有效性：超过配置的有效月数未体检判为已到期。"""
    if not last_checkup_date:
        return "未体检"
    start = personnel_service.parse_datetime(last_checkup_date, with_time=False)
    if start is None:
        return "未体检"
    now = datetime.datetime.now()
    months = (now.year - start.year) * 12 + (now.month - start.month)
    if now.day < start.day:
        months -= 1
    return "已到期" if months >= database.get_int(
        "checkup_expire_months", config.CHECKUP_EXPIRE_MONTHS) else "有效"


def _chronic_text(row):
    labels = [label for key, label in config.CHRONIC_KEYS if row.get(key)]
    return "、".join(labels) if labels else "—"


# ---------------------------------------------------------------- 健康档案
def get_profile(person_id):
    row = database.fetch_one("SELECT * FROM health_profile WHERE person_id = ?",
                             (person_id,))
    return dict(row) if row else None


def save_profile(person_id, data, operator):
    """新增或更新健康档案；BMI 由身高体重自动计算。返回 (是否成功, 提示)。"""
    person = personnel_service.get_person(person_id)
    if person is None:
        return False, "人员不存在"

    blood_type = (data.get("blood_type") or "未知").strip()
    if blood_type not in config.BLOOD_TYPES:
        return False, "血型只能为 " + " / ".join(config.BLOOD_TYPES)
    rh_type = (data.get("rh_type") or "未知").strip()
    if rh_type not in config.RH_TYPES:
        return False, "Rh 只能为 " + " / ".join(config.RH_TYPES)

    checkup_date = (data.get("last_checkup_date") or "").strip()
    if checkup_date:
        if personnel_service.parse_datetime(checkup_date, with_time=False) is None:
            return False, "体检日期格式应为 2026-10-01"
        checkup_date = checkup_date[:10]

    height = _to_float(data.get("height_cm"))
    weight = _to_float(data.get("weight_kg"))
    if height is not None and not 80 <= height <= 250:
        return False, "身高需在 80–250 cm 之间"
    if weight is not None and not 20 <= weight <= 300:
        return False, "体重需在 20–300 kg 之间"
    bmi = calc_bmi(height, weight)

    chronic = {key: 1 if data.get(key) else 0 for key, _label in config.CHRONIC_KEYS}
    fields = (
        height, weight, bmi, blood_type, rh_type, checkup_date,
        (data.get("checkup_org") or "").strip(),
        (data.get("medical_history") or "").strip(),
        (data.get("surgery_history") or "").strip(),
        (data.get("allergy_history") or "").strip(),
        chronic["heart_disease"], chronic["diabetes"], chronic["hypertension"],
        chronic["occupational_disease"], (data.get("occupational_desc") or "").strip(),
        database.now_str(),
    )

    with database.get_connection() as conn:
        if conn.execute("SELECT 1 FROM health_profile WHERE person_id = ?",
                        (person_id,)).fetchone():
            conn.execute(
                "UPDATE health_profile SET height_cm = ?, weight_kg = ?, bmi = ?,"
                " blood_type = ?, rh_type = ?, last_checkup_date = ?, checkup_org = ?,"
                " medical_history = ?, surgery_history = ?, allergy_history = ?,"
                " heart_disease = ?, diabetes = ?, hypertension = ?,"
                " occupational_disease = ?, occupational_desc = ?, updated_at = ?"
                " WHERE person_id = ?", fields + (person_id,))
        else:
            conn.execute(
                "INSERT INTO health_profile(person_id, height_cm, weight_kg, bmi,"
                " blood_type, rh_type, last_checkup_date, checkup_org, medical_history,"
                " surgery_history, allergy_history, heart_disease, diabetes,"
                " hypertension, occupational_disease, occupational_desc, updated_at,"
                " parse_status) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?, '未解析')",
                (person_id,) + fields)

    database.write_op_log(personnel_service.operator_id(operator), "健康管理",
                          "保存健康档案", person["emp_no"],
                          f"{person['name']}｜BMI {bmi if bmi else '—'}"
                          f"｜体检 {checkup_date or '—'}")
    return True, f"{person['name']} 的健康档案已保存"


def list_profiles(keyword=None, unit=None, person_type=None, only_onboard=True,
                  only_missing=False, platform_id=platform_service._UNSET):
    """人员与档案合并视图，附体检状态与慢病标记。"""
    where = ["p.deleted = 0"]
    params = []
    scope_sql, scope_params = platform_service.platform_clause("p", platform_id)
    if scope_sql:
        where.append(scope_sql)
        params.extend(scope_params)
    if only_onboard:
        where.append("p.status = ?")
        params.append(config.PERSON_STATUS_ONBOARD)
    if person_type:
        where.append("p.person_type = ?")
        params.append(person_type)
    if unit:
        where.append("p.unit = ?")
        params.append(unit)
    if keyword:
        where.append("(p.emp_no LIKE ? OR p.name LIKE ?)")
        params.extend([f"%{keyword}%", f"%{keyword}%"])
    if only_missing:
        where.append("h.id IS NULL")
    clause = " WHERE " + " AND ".join(where)

    rows = database.fetch_all(
        "SELECT p.id, p.emp_no, p.name, p.gender, p.age, p.unit, p.person_type,"
        " p.status, h.id AS profile_id, h.height_cm, h.weight_kg, h.bmi, h.blood_type,"
        " h.rh_type, h.last_checkup_date, h.checkup_org, h.checkup_report_path,"
        " h.parse_status, h.medical_history, h.surgery_history, h.allergy_history,"
        " h.heart_disease, h.diabetes, h.hypertension, h.occupational_disease,"
        " h.occupational_desc"
        " FROM personnel p LEFT JOIN health_profile h ON h.person_id = p.id"
        f"{clause} ORDER BY p.emp_no LIMIT 2000", params)

    records = []
    for row in rows:
        item = dict(row)
        item["has_profile"] = item["profile_id"] is not None
        item["checkup_level"] = checkup_level(item["last_checkup_date"])
        item["chronic_text"] = _chronic_text(item)
        records.append(item)
    return records


def confirm_parse(person_id, operator):
    """人工核对通过：解析状态置为已确认。"""
    person = personnel_service.get_person(person_id)
    if person is None:
        return False, "人员不存在"
    profile = get_profile(person_id)
    if profile is None:
        return False, "尚未建立健康档案"
    if profile["parse_status"] != "待核对":
        return False, "当前没有待核对的解析结果"
    with database.get_connection() as conn:
        conn.execute("UPDATE health_profile SET parse_status = '已确认', updated_at = ?"
                     " WHERE person_id = ?", (database.now_str(), person_id))
    database.write_op_log(personnel_service.operator_id(operator), "健康管理",
                          "确认体检解析", person["emp_no"], person["name"])
    return True, f"{person['name']} 的体检解析结果已确认"


# ---------------------------------------------------------------- 体检报告
def report_abs_path(rel_path):
    return config.APP_DIR / rel_path


def parse_report(path):
    """用 pdfplumber 解析标准模板报告，返回提取到的字段；失败返回 {}。"""
    if Path(path).suffix.lower() != ".pdf":
        return {}
    try:
        import pdfplumber
    except ImportError:
        return {}
    try:
        with pdfplumber.open(str(path)) as pdf:
            text = "\n".join((page.extract_text() or "") for page in pdf.pages)
    except Exception:                                  # noqa: BLE001 解析异常降级为人工录入
        return {}
    if not text.strip():
        return {}

    result = {}
    for key, pattern in _PATTERNS.items():
        match = re.search(pattern, text)
        if match:
            result[key] = match.group(1)
    blood = _BLOOD_RE.search(text)
    if blood:
        result["blood_type"] = blood.group(1)
    rh = _RH_RE.search(text)
    if rh:
        result["rh_type"] = "阳性" if rh.group(1) in ("阳性", "＋", "+") else "阴性"
    org = _ORG_RE.search(text)
    if org:
        result["checkup_org"] = org.group(1).strip()
    date = _DATE_RE.search(text)
    if date:
        result["last_checkup_date"] = "{}-{:02d}-{:02d}".format(
            date.group(1), int(date.group(2)), int(date.group(3)))
    return result


def attach_report(person_id, src_path, checkup_date, operator):
    """归档体检报告：按 attachments/工号/日期.扩展名 存放，并尝试自动解析。"""
    person = personnel_service.get_person(person_id)
    if person is None:
        return False, "人员不存在"
    source = Path(src_path)
    if not source.is_file():
        return False, "报告文件不存在"
    if source.suffix.lower() not in config.REPORT_EXTENSIONS:
        return False, "仅支持 PDF / JPG / PNG 格式的体检报告"

    parsed = parse_report(source)
    date_text = (checkup_date or "").strip()[:10] \
        or parsed.get("last_checkup_date") \
        or datetime.datetime.now().strftime("%Y-%m-%d")
    if personnel_service.parse_datetime(date_text, with_time=False) is None:
        return False, "体检日期格式应为 2026-10-01"

    target_dir = config.ATTACH_DIR / str(person["emp_no"])
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{date_text}{source.suffix.lower()}"
    try:
        if source.resolve() != target.resolve():
            shutil.copy2(source, target)
    except OSError as exc:
        return False, f"报告归档失败：{exc}"
    rel_path = target.relative_to(config.APP_DIR).as_posix()

    status = "待核对" if parsed else "未解析"

    existing = get_profile(person_id) or {}
    height = _to_float(parsed.get("height_cm")) or existing.get("height_cm")
    weight = _to_float(parsed.get("weight_kg")) or existing.get("weight_kg")
    bmi = calc_bmi(height, weight)
    checkup_org = parsed.get("checkup_org") or existing.get("checkup_org") or ""
    real_date = parsed.get("last_checkup_date") or date_text
    blood_type = parsed.get("blood_type") or existing.get("blood_type") or "未知"
    rh_type = parsed.get("rh_type") or existing.get("rh_type") or "未知"

    with database.get_connection() as conn:
        if not existing:
            conn.execute(
                "INSERT INTO health_profile(person_id, height_cm, weight_kg, bmi,"
                " blood_type, rh_type, last_checkup_date, checkup_org,"
                " checkup_report_path, parse_status, updated_at)"
                " VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (person_id, height, weight, bmi, blood_type, rh_type, real_date,
                 checkup_org, rel_path, status, database.now_str()))
        else:
            conn.execute(
                "UPDATE health_profile SET height_cm = ?, weight_kg = ?, bmi = ?,"
                " blood_type = ?, rh_type = ?, last_checkup_date = ?, checkup_org = ?,"
                " checkup_report_path = ?, parse_status = ?, updated_at = ?"
                " WHERE person_id = ?",
                (height, weight, bmi, blood_type, rh_type, real_date, checkup_org,
                 rel_path, status, database.now_str(), person_id))

    database.write_op_log(personnel_service.operator_id(operator), "健康管理",
                          "归档体检报告", person["emp_no"],
                          f"{person['name']}｜{target.name}｜{status}")
    if parsed:
        return True, (f"{person['name']} 的报告已归档（{target.name}），"
                      f"自动解析到 {len(parsed)} 项信息，请人工核对后确认")
    return True, f"{person['name']} 的报告已归档（{target.name}），未能自动解析，请人工录入"


def _match_person(text):
    """按文件名中出现的工号匹配人员，取最长匹配避免歧义（限当前平台范围）。"""
    scope_sql, scope_params = platform_service.platform_clause("personnel")
    clause = f" AND {scope_sql}" if scope_sql else ""
    best = None
    for row in database.fetch_all(
            f"SELECT id, emp_no, name FROM personnel WHERE deleted = 0{clause}",
            scope_params):
        emp_no = row["emp_no"]
        if emp_no and emp_no in text:
            if best is None or len(emp_no) > len(best["emp_no"]):
                best = dict(row)
    return best


def import_report_folder(folder, operator):
    """批量导入文件夹内报告，按文件名中的工号归档。返回 (是否成功, 提示, 明细)。"""
    folder = Path(folder)
    if not folder.is_dir():
        return False, "文件夹不存在", []
    files = [path for path in sorted(folder.rglob("*"))
             if path.is_file() and path.suffix.lower() in config.REPORT_EXTENSIONS]
    if not files:
        return False, "文件夹内未找到 PDF / JPG / PNG 报告", []

    results = []
    for path in files:
        person = _match_person(path.stem)
        if person is None:
            results.append({"file": path.name, "ok": False,
                            "message": "文件名中未匹配到工号"})
            continue
        ok, message = attach_report(person["id"], path, None, operator)
        results.append({"file": path.name, "ok": ok, "message": message,
                        "emp_no": person["emp_no"], "name": person["name"]})
    success = sum(1 for item in results if item["ok"])
    return True, f"共处理 {len(files)} 份报告，成功 {success} 份", results


# ---------------------------------------------------------------- 日常监测
def save_check(person_id, values, recorder, note="", check_date=None):
    """录入日常监测：自动分级并记录异常项。返回 (是否成功, 提示, 级别)。"""
    person = personnel_service.get_person(person_id)
    if person is None:
        return False, "人员不存在", None

    check_date = (check_date or "").strip() or \
        datetime.datetime.now().strftime("%Y-%m-%d")
    if personnel_service.parse_datetime(check_date, with_time=False) is None:
        return False, "监测日期格式应为 2026-10-01", None
    check_date = check_date[:10]

    cleaned = {}
    for key, label, _unit in config.MONITOR_FIELDS:
        raw = values.get(key)
        if raw in (None, ""):
            cleaned[key] = None
            continue
        number = _to_float(raw)
        if number is None:
            return False, f"{label}需为数字", None
        cleaned[key] = number
    if all(value is None for value in cleaned.values()):
        return False, "请至少填写一项监测指标", None

    profile = get_profile(person_id) or {}
    bmi = calc_bmi(profile.get("height_cm"), cleaned.get("weight_kg"))
    if cleaned.get("weight_kg") is not None:
        cleaned["bmi"] = bmi

    level, items = evaluate_indicators(cleaned)
    abnormal_text = "；".join(item["text"] for item in items)

    with database.get_connection() as conn:
        conn.execute(
            "INSERT INTO daily_check(person_id, check_date, systolic, diastolic,"
            " blood_sugar, weight_kg, homocysteine, cholesterol, ldl_c, hdl_c,"
            " abnormal_level, abnormal_items, recorder, note)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (person_id, check_date, cleaned.get("systolic"), cleaned.get("diastolic"),
             cleaned.get("blood_sugar"), cleaned.get("weight_kg"),
             cleaned.get("homocysteine"), cleaned.get("cholesterol"),
             cleaned.get("ldl_c"), cleaned.get("hdl_c"),
             level, abnormal_text, recorder, note))
        if cleaned.get("weight_kg") is not None and profile:
            conn.execute("UPDATE health_profile SET weight_kg = ?, bmi = ?, updated_at = ?"
                         " WHERE person_id = ?",
                         (cleaned["weight_kg"], bmi, database.now_str(), person_id))

    database.write_op_log(personnel_service.operator_id(recorder), "健康管理",
                          "录入日常监测", person["emp_no"],
                          f"{person['name']}｜{check_date}｜{level}"
                          f"{'｜' + abnormal_text if abnormal_text else ''}")
    message = f"{person['name']} {check_date} 的监测记录已保存"
    if items:
        message += f"，{level} {len(items)} 项：{abnormal_text}"
    return True, message, level


def save_checks_batch(entries, recorder, check_date=None, note=""):
    """批量录入日常监测：逐条调用 save_check，单条失败不中断整体。

    entries: [{"person_id": int, "values": {字段: 值}, "note": 可选}]。
    全部指标为空的条目跳过（视为该人员尚未填写）。
    返回 (处理条数, 成功数, 失败数, 明细列表)。
    """
    results = []
    ok_count = 0
    for item in entries:
        values = item.get("values") or {}
        if not any(str(raw or "").strip() for raw in values.values()):
            continue                               # 未填写任何指标 → 跳过
        person_id = item.get("person_id")
        person = personnel_service.get_person(person_id) or {}
        ok, message, level = save_check(
            person_id, values, recorder, note=item.get("note", note),
            check_date=check_date)
        results.append({"emp_no": person.get("emp_no", ""),
                        "name": person.get("name", ""),
                        "ok": ok, "message": message, "level": level})
        if ok:
            ok_count += 1
    return len(results), ok_count, len(results) - ok_count, results


def list_checks(person_id=None, keyword=None, unit=None, level=None, limit=200,
                platform_id=platform_service._UNSET):
    where = []
    params = []
    scope_sql, scope_params = platform_service.platform_clause("p", platform_id)
    if scope_sql:
        where.append(scope_sql)
        params.extend(scope_params)
    if person_id:
        where.append("d.person_id = ?")
        params.append(person_id)
    if level:
        where.append("d.abnormal_level = ?")
        params.append(level)
    if unit:
        where.append("p.unit = ?")
        params.append(unit)
    if keyword:
        where.append("(p.emp_no LIKE ? OR p.name LIKE ?)")
        params.extend([f"%{keyword}%", f"%{keyword}%"])
    clause = (" WHERE " + " AND ".join(where)) if where else ""
    rows = database.fetch_all(
        "SELECT d.*, p.emp_no, p.name, p.unit, p.person_type FROM daily_check d"
        f" JOIN personnel p ON p.id = d.person_id{clause}"
        " ORDER BY d.check_date DESC, d.id DESC LIMIT ?", params + [limit])
    return [dict(row) for row in rows]


def monitor_summary(unit=None, person_type=None, start=None, end=None, limit=20000,
                    platform_id=platform_service._UNSET):
    """日常监测汇总（按单位 / 人员类型导出用）：人员信息 + 8 项指标 + 预警级别。"""
    where = ["p.deleted = 0"]
    params = []
    scope_sql, scope_params = platform_service.platform_clause("p", platform_id)
    if scope_sql:
        where.append(scope_sql)
        params.extend(scope_params)
    if unit:
        where.append("p.unit = ?")
        params.append(unit)
    if person_type:
        where.append("p.person_type = ?")
        params.append(person_type)
    if start:
        where.append("d.check_date >= ?")
        params.append(start)
    if end:
        where.append("d.check_date <= ?")
        params.append(end)
    clause = " WHERE " + " AND ".join(where)
    rows = database.fetch_all(
        "SELECT p.emp_no, p.name, p.unit, p.person_type, d.check_date, d.systolic,"
        " d.diastolic, d.blood_sugar, d.weight_kg, d.homocysteine, d.cholesterol,"
        " d.ldl_c, d.hdl_c, d.abnormal_level, d.abnormal_items, d.recorder, d.note"
        " FROM daily_check d JOIN personnel p ON p.id = d.person_id" + clause +
        " ORDER BY d.check_date DESC, p.emp_no LIMIT ?", params + [limit])
    return [dict(row) for row in rows]


def delete_check(check_id, operator):
    row = database.fetch_one(
        "SELECT d.check_date, d.abnormal_level, p.emp_no, p.name FROM daily_check d"
        " JOIN personnel p ON p.id = d.person_id WHERE d.id = ?", (check_id,))
    if row is None:
        return False, "监测记录不存在"
    with database.get_connection() as conn:
        conn.execute("DELETE FROM daily_check WHERE id = ?", (check_id,))
    database.write_op_log(personnel_service.operator_id(operator), "健康管理",
                          "删除日常监测", row["emp_no"],
                          f"{row['name']}｜{row['check_date']}｜{row['abnormal_level']}")
    return True, f"已删除 {row['name']} {row['check_date']} 的监测记录"


def check_trend(person_id, indicator_key):
    """个人单项指标趋势：返回 [(日期, 数值)]。"""
    if indicator_key not in _CHECK_COLUMNS:
        return []
    rows = database.fetch_all(
        f"SELECT check_date, {indicator_key} AS value FROM daily_check"
        f" WHERE person_id = ? AND {indicator_key} IS NOT NULL"
        " ORDER BY check_date LIMIT 200", (person_id,))
    return [(row["check_date"], row["value"]) for row in rows]


# ---------------------------------------------------------------- 预警统计
def checkup_warnings():
    """在平台人员中体检未做或已到期的名单。"""
    return [row for row in list_profiles(only_onboard=True)
            if row["checkup_level"] in ("未体检", "已到期")]


def latest_abnormal_persons(limit=200, platform_id=platform_service._UNSET):
    """每人最新一次监测中处于预警状态的人员。"""
    scope_sql, scope_params = platform_service.platform_clause("p", platform_id)
    scope = f" AND {scope_sql}" if scope_sql else ""
    rows = database.fetch_all(
        "SELECT d.*, p.emp_no, p.name, p.unit, p.person_type FROM daily_check d"
        " JOIN personnel p ON p.id = d.person_id"
        " WHERE d.id IN (SELECT MAX(id) FROM daily_check GROUP BY person_id)"
        f" AND d.abnormal_level <> '正常'{scope}"
        " ORDER BY CASE d.abnormal_level WHEN '红色报警' THEN 0 ELSE 1 END,"
        " d.check_date DESC LIMIT ?", scope_params + [limit])
    return [dict(row) for row in rows]


def indicator_abnormal_counts(platform_id=platform_service._UNSET):
    """最新监测中各项指标的异常人数，用于健康异常构成统计。"""
    counter = {}
    for row in latest_abnormal_persons(limit=10000, platform_id=platform_id):
        for text in (row["abnormal_items"] or "").split("；"):
            text = text.strip()
            if text:
                label = text.split(" ")[0]
                counter[label] = counter.get(label, 0) + 1
    return counter


def health_summary():
    """供状态栏与看板使用的健康概览。"""
    return {"abnormal": len(latest_abnormal_persons(limit=10000)),
            "checkup_due": len(checkup_warnings())}