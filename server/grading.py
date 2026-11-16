"""Zhengzhou University undergraduate percentage marks, 校教务〔2024〕8号, art. 12."""
import math


POLICY_ID = "zzu-undergrad-2024-8-art12-v1"
SOURCE_URL = "https://www5.zzu.edu.cn/__local/9/4B/6E/0D5C783280332442F426D639EBE_CED7A822_48019B.pdf#page=5"
SOURCE_TITLE = "《郑州大学普通本科生学籍管理规定》第十二条"
BANDS = ((90, 4.0), (85, 3.7), (80, 3.2), (75, 2.7),
         (70, 2.2), (65, 1.7), (60, 1.2), (0, 0.0))
COURSE_NATURES = {"必修", "限选", "任选"}
METHOD = "按校教务〔2024〕8号第十二条将百分制记载成绩分档换算，再按课程学分加权。任选课不计入平均绩点，课程性质待核实的单独提示。"


def grade_point(score):
    if score is None:
        return None
    if not math.isfinite(score) or not 0 <= score <= 100:
        raise ValueError("百分制记载成绩应在 0 到 100 之间")
    return next(points for minimum, points in BANDS if score >= minimum)


def gpa_scope(course, language):
    """A general '选修' or a false required flag alone does not establish 任选."""
    if course is None:
        return "unconfirmed"
    meta = course["meta"]
    nature = meta.get("courseNature")
    if isinstance(nature, str) and nature in COURSE_NATURES:
        return "excluded" if nature == "任选" else "included"
    module = meta.get("submodule", "")
    if module in ("进阶任选", "核心通识任选", "任选", "任选课"):
        return "excluded"
    if meta.get("language"):
        return "included" if meta["language"] == language else "unconfirmed"
    if course["required"] or meta.get("requiredInModule") or module in ("进阶限选", "限选", "限选课"):
        return "included"
    # Older copies of these five project-created demo electives predate courseNature.
    if meta.get("isSimulated") and course["code"] in ("SIM-ART", "SIM-SCI", "SIM-CUL", "SIM-SOC", "SIM-CROSS"):
        return "excluded"
    return "unconfirmed"


def weighted_gpa(records, courses, scopes):
    total, weight = 0.0, 0.0
    for record in records:
        cid = record["course_id"]
        if scopes.get(cid) != "included" or record["score"] is None:
            continue
        credits = courses[cid]["credits"]
        total += grade_point(record["score"]) * credits
        weight += credits
    return total / weight if weight else None
