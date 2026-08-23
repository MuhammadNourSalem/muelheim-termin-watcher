"""
مراقب مواعيد مكتب الأجانب (Ausländeramt) - Mülheim an der Ruhr
================================================================
نسخة GitHub Actions: فحص واحد لكل تشغيل، تُقرأ بيانات تيليجرام من
GitHub Secrets (متغيرات بيئة)، ويشتغل السيرفر بدون واجهة (headless)
دائماً. الجدولة المتكررة تتم عبر ملف .github/workflows/check.yml
"""

import time
import logging
from datetime import datetime

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
import requests

# ============================== CONFIG ==============================

# رابط بداية الحجز - عدّله لو تغيّر (لاحظ الموقع أعاد التوجيه إلى
# ابدومين abe.muelheim-ruhr.de عند اختيار Ausländeramt)
START_URL = "https://terminvergabe.muelheim-ruhr.de/"

# بيانات بوت تيليجرام - تُقرأ من GitHub Secrets (متغيرات بيئة) وليس من
# داخل الكود، لأن الريبو غالباً يكون عاماً (public) ولا يجوز كتابة
# التوكن بشكل صريح بملف مرفوع على GitHub
import os

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
    raise SystemExit(
        "❌ لم يتم العثور على TELEGRAM_BOT_TOKEN أو TELEGRAM_CHAT_ID "
        "كمتغيرات بيئة. تأكد من إضافتهما كـ GitHub Secrets."
    )

# نص الوظيفة المطلوبة في الخطوة 1 والفئة في الخطوة 2
FUNKTIONSEINHEIT = "Ausländeramt"
KATEGORIE = "Studierende und Anerkennung der Berufsqualifikation"
ANLIEGEN = "Anmeldung"  # الخدمة المطلوبة (زر + يُضغط مرة واحدة)

# النص الذي يظهر عند عدم توفر مواعيد (من صورة الخطوة 4)
NO_APPOINTMENT_TEXT = "Kein freier Termin verfügbar"

# لازم True دائماً على GitHub Actions (لا توجد شاشة/واجهة على السيرفر)
HEADLESS = True

# ============================== LOGGING ==============================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("termin_monitor.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger(__name__)


import json

RUN_LOG_FILE = "run_log.json"


def log_run(available: bool):
    """يسجل وقت ونتيجة هذا التشغيل بملف JSON، عشان التقرير اليومي يقرأه لاحقاً."""
    try:
        try:
            with open(RUN_LOG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            data = []

        data.append({
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "available": available,
        })

        with open(RUN_LOG_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log.warning(f"تعذّر تسجيل هذا التشغيل بملف السجل: {e}")


def send_telegram(message: str, photo_path: str | None = None):
    """يرسل رسالة (ويمكن صورة) عبر بوت تيليجرام."""
    try:
        base = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"
        if photo_path:
            with open(photo_path, "rb") as f:
                requests.post(
                    f"{base}/sendPhoto",
                    data={"chat_id": TELEGRAM_CHAT_ID, "caption": message},
                    files={"photo": f},
                    timeout=15,
                )
        else:
            requests.post(
                f"{base}/sendMessage",
                data={"chat_id": TELEGRAM_CHAT_ID, "text": message},
                timeout=15,
            )
        log.info("تم إرسال تنبيه تيليجرام.")
    except Exception as e:
        log.error(f"فشل إرسال تنبيه تيليجرام: {e}")


def click_weiter(page, timeout: int = 15000):
    """
    يضغط زر 'Weiter' مباشرة عبر id الثابت #WeiterButton (أسرع وأدق من
    البحث بالنص). لو لم يوجد لأي سبب، يرجع للبحث بالنص كخطة بديلة.
    """
    try:
        btn = page.locator("#WeiterButton")
        btn.wait_for(state="visible", timeout=timeout)
        btn.scroll_into_view_if_needed(timeout=3000)
        btn.click(timeout=5000)
        return
    except Exception:
        log.info("لم يُعثر على #WeiterButton مباشرة، جاري المحاولة بالبحث النصي...")
        click_visible_text(page, "Weiter", timeout=timeout)


def click_visible_text(page, text: str, timeout: int = 15000):
    """
    يبحث عن كل العناصر التي تحتوي النص المعطى، ويضغط أول عنصر
    ظاهر فعلياً على الشاشة (يتجاهل عناصر accessibility/tooltip المخفية
    التي تحمل نفس النص).
    """
    deadline = time.time() + (timeout / 1000)
    while time.time() < deadline:
        candidates = page.get_by_text(text, exact=False).all()
        for el in candidates:
            try:
                if el.is_visible():
                    el.click(timeout=3000)
                    return
            except Exception:
                continue
        page.wait_for_timeout(300)
    raise PWTimeout(f"لم يتم العثور على عنصر مرئي يحتوي النص: {text}")


def _get_step_number(page) -> int | None:
    """يحاول استخراج رقم الخطوة الحالية من عنوان الصفحة (مثل 'Schritt 3')."""
    import re
    try:
        heading = page.locator("text=/Schritt\\s*\\d+/").first
        text = heading.inner_text(timeout=3000)
        match = re.search(r"Schritt\s*(\d+)", text)
        if match:
            return int(match.group(1))
    except Exception:
        pass
    return None


def _log_current_step(page):
    """يسجل رقم وعنوان الخطوة الحالية بملف اللوج للمساعدة بالتشخيص."""
    try:
        heading = page.locator("text=/Schritt\\s*\\d+/").first
        text = heading.inner_text(timeout=3000)
        log.info(f"الخطوة الحالية بالصفحة: {text}")
    except Exception:
        log.info("تعذّر تحديد رقم/عنوان الخطوة الحالية.")


def handle_document_checklist_modal(page) -> bool:
    """
    يتعامل مع نافذة 'Hinweis' المنبثقة التي تطلب تأكيد توفر كل المستندات
    المطلوبة (قائمة صناديق اختيار فارغة) قبل المتابعة. يضغط على كل صندوق
    عبر الـ label المرئي (وليس الـ checkbox المخفي مباشرة، لأن الموقع
    يستخدم تصميم مخصص يعتمد على ضغطة فعلية على العنصر المرئي لتفعيل
    منطق التحقق بالجافاسكريبت)، ثم ينتظر تفعّل زر OK ويضغطه.
    يرجع True لو ظهرت النافذة وتم التعامل معها.
    """
    try:
        modal_heading = page.get_by_text("Hinweis", exact=True).first
        modal_heading.wait_for(state="visible", timeout=5000)
    except Exception:
        return False  # لا توجد نافذة منبثقة، تابع عادي

    log.info("ظهرت نافذة قائمة المستندات المطلوبة - جاري تحديد كل الصناديق...")

    # الأولوية: الضغط على الـ label المرئي المرتبط بكل checkbox (هو العنصر
    # الفعلي الذي يستقبل ضغطات المستخدم بصرياً في هذا التصميم المخصص)
    checkboxes = page.locator('input[type="checkbox"]')
    count = checkboxes.count()
    clicked_count = 0

    for i in range(count):
        cb = checkboxes.nth(i)
        try:
            if not cb.is_visible():
                continue
            if cb.is_checked():
                clicked_count += 1
                continue

            cb_id = cb.get_attribute("id")
            clicked = False

            # المحاولة 1: الضغط على أي label مرتبط بنفس الـ id (الصندوق المرئي)
            if cb_id:
                labels = page.locator(f'label[for="{cb_id}"]')
                label_count = labels.count()
                for j in range(label_count):
                    lbl = labels.nth(j)
                    if lbl.is_visible():
                        lbl.click(timeout=3000)
                        clicked = True
                        break

            # المحاولة 2: لو ما فيه label مرئي مرتبط، اضغط الـ checkbox مباشرة
            if not clicked:
                cb.check(timeout=3000)
                clicked = True

            clicked_count += 1
        except Exception as e:
            log.warning(f"تعذّر تحديد صندوق اختيار رقم {i}: {e}")
            continue

    log.info(f"تم تحديد {clicked_count} من أصل {count} صندوق اختيار داخل النافذة المنبثقة.")

    # انتظار زر OK حتى يصبح فعّالاً (غير معطّل) قبل الضغط عليه
    ok_button = None
    deadline = time.time() + 10
    while time.time() < deadline:
        candidates = page.get_by_text("OK", exact=True).all()
        for el in candidates:
            try:
                if el.is_visible() and el.get_attribute("disabled") is None:
                    ok_button = el
                    break
            except Exception:
                continue
        if ok_button:
            break
        page.wait_for_timeout(300)

    if ok_button is None:
        # حفظ HTML النافذة المنبثقة للتشخيص لو استمرت المشكلة
        try:
            modal_html = page.locator("body").evaluate(
                "el => { const m = el.querySelector('.modal, [role=dialog]'); "
                "return m ? m.outerHTML : 'لم يتم العثور على حاوية النافذة المنبثقة'; }"
            )
            with open("debug_hinweis_modal.html", "w", encoding="utf-8") as f:
                f.write(modal_html)
            log.error("زر OK لم يُفعّل. تم حفظ HTML النافذة بـ debug_hinweis_modal.html للتشخيص.")
        except Exception as dump_err:
            log.error(f"فشل حفظ HTML النافذة: {dump_err}")
        raise Exception("تعذّر تفعيل/الضغط على زر OK بالنافذة المنبثقة")

    ok_button.click(timeout=5000)
    page.wait_for_load_state("networkidle")
    return True


def accept_cookies(page):
    """يقبل بانر الكوكيز إذا ظهر (Akzeptieren)، بدون توقف لو لم يظهر."""
    try:
        btn = page.get_by_text("Akzeptieren", exact=True).first
        btn.wait_for(state="visible", timeout=6000)
        btn.click(timeout=5000)
        log.info("تم قبول بانر الكوكيز.")
    except Exception:
        log.info("لم يظهر بانر كوكيز (أو تم تجاوزه).")


def check_appointment() -> tuple[bool, str]:
    """
    يمشي خطوات الحجز 1-4 ويرجع (توفر_موعد, مسار_لقطة_الشاشة).
    """
    screenshot_path = f"step4_{datetime.now():%Y%m%d_%H%M%S}.png"

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=HEADLESS)
        page = browser.new_page()

        try:
            # ---------- فتح الصفحة ----------
            page.goto(START_URL, wait_until="networkidle", timeout=30000)
            accept_cookies(page)

            # ---------- الخطوة 1: اختيار الوظيفة ----------
            click_visible_text(page, FUNKTIONSEINHEIT)
            page.wait_for_load_state("networkidle")
            accept_cookies(page)

            # ---------- الخطوة 2: اختيار الفئة ثم الأنليغن ----------
            # فتح القسم (accordion) الخاص بالفئة إن لم يكن مفتوحاً
            click_visible_text(page, KATEGORIE)

            # زيادة عداد "Anmeldung" بالضغط على زر + الخاص به تحديداً
            # (نعتمد على data-attributes إنجليزية بالكامل لتفادي مشاكل
            # ترميز الأحرف الألمانية مثل ö عند المطابقة النصية)
            # يوجد أكثر من حقل بنفس data-tevis-cncname تحت فئات مختلفة
            # (بعضها مخفي بالأكورديون وليس محذوفاً من الصفحة) -> نفلتر للمرئي فقط
            all_inputs = page.locator(f'input[data-tevis-cncname="{ANLIEGEN}"]')
            count = all_inputs.count()
            input_field = None
            for i in range(count):
                candidate = all_inputs.nth(i)
                if candidate.is_visible():
                    input_field = candidate
                    break
            if input_field is None:
                raise Exception(f"لم يتم العثور على حقل {ANLIEGEN} مرئي بين {count} عنصر")

            # نلتقط id الفريد للحقل الصحيح عشان نتحقق منه بدقة بعد الضغط
            input_id = input_field.get_attribute("id")

            container = input_field.locator(
                "xpath=ancestor::div[contains(@id,'inputBox')][1]"
            )
            plus_button = container.locator('button[data-type="plus"]')
            plus_button.wait_for(state="visible", timeout=10000)
            plus_button.click(timeout=10000)

            # تحقق: تأكد أن القيمة أصبحت 1 فعلاً بنفس الحقل المحدد (عبر id الفريد)
            page.wait_for_function(
                """(id) => {
                    const el = document.getElementById(id);
                    return el && el.value === '1';
                }""",
                arg=input_id,
                timeout=5000,
            )
            log.info(f"تم ضبط {ANLIEGEN} = 1 بنجاح.")

            # زر "Weiter" (التالي) للانتقال من الخطوة 2
            click_weiter(page)
            page.wait_for_load_state("networkidle")
            handle_document_checklist_modal(page)
            _log_current_step(page)

            # ---------- الخطوات 3 (وربما أكثر) حتى الوصول للخطوة 4 ----------
            # نحاول الضغط على Weiter بشكل متكرر (حتى 3 محاولات إضافية)
            # لحين الوصول فعلياً للخطوة 4، مع تسجيل كل خطوة للتشخيص
            for attempt in range(3):
                step_num = _get_step_number(page)
                if step_num == 4:
                    break
                log.info(f"لم نصل بعد للخطوة 4 (الحالية: {step_num}) - محاولة الضغط على Weiter مجدداً...")
                try:
                    click_weiter(page, timeout=8000)
                    page.wait_for_load_state("networkidle")
                    handle_document_checklist_modal(page)
                    _log_current_step(page)
                except PWTimeout:
                    log.warning("لم يُعثر على زر Weiter مرئي - قد تحتاج الخطوة الحالية تدخلاً يدوياً (مثل اختيار حقل).")
                    break

            # ---------- الخطوة 4: النتيجة ----------
            final_step = _get_step_number(page)
            if final_step != 4:
                diag_shot = f"stuck_step_{final_step}_{datetime.now():%Y%m%d_%H%M%S}.png"
                page.screenshot(path=diag_shot, full_page=True)
                log.error(
                    f"لم يصل السكربت للخطوة 4 (توقف عند: {final_step}). "
                    f"تم حفظ لقطة شاشة بـ: {diag_shot} - أرسلها للتشخيص."
                )
                browser.close()
                return False, ""

            page.wait_for_selector("text=Schritt 4", timeout=20000)
            page.screenshot(path=screenshot_path, full_page=True)

            page_content = page.content()
            no_appointment = NO_APPOINTMENT_TEXT in page_content

            browser.close()
            return (not no_appointment), screenshot_path

        except Exception as e:
            log.error(f"خطأ أثناء الفحص: {e}")
            try:
                page.screenshot(path=f"error_{datetime.now():%Y%m%d_%H%M%S}.png")
            except Exception:
                pass
            browser.close()
            return False, ""


def main():
    """
    فحص واحد فقط في كل تشغيل - مصمم ليعمل عبر GitHub Actions المجدول
    (Scheduled Workflow) بدل الحلقة اللانهائية. GitHub نفسه هو من يعيد
    تشغيل هذا الملف كل فترة زمنية محددة بملف الجدولة .yml
    """
    log.info("بدء فحص مواعيد Ausländeramt مولهايم (تشغيل واحد)...")
    send_telegram("🟢 بدأ تشغيل السكربت (فحص جديد).")

    try:
        available, screenshot = check_appointment()
        log_run(available)
    except Exception as e:
        log.error(f"خطأ عام: {e}")
        log_run(False)
        # لا نرسل تنبيه تيليجرام لكل خطأ عابر تجنباً لإزعاج متكرر؛
        # سجلات GitHub Actions نفسها كافية لمراجعة الأخطاء عند الحاجة
        return

    if available:
        log.info("🎉 يوجد موعد متاح!")
        send_telegram(
            "🎉 تنبيه: يوجد موعد متاح الآن في مكتب الأجانب - مولهايم!\n"
            "افتح الرابط بسرعة وأكمل الحجز:\n" + START_URL,
            photo_path=screenshot,
        )
    else:
        log.info("لا يوجد موعد حالياً.")


if __name__ == "__main__":
    main()
